# -*- coding: utf-8 -*-
"""
CreateFlowArrow.pyt
-------------------
Unified ArcGIS Python Toolbox for generating flow direction arrows and
conducting automated QA/QC slope & flow direction audits on gravity infrastructure networks.

Fully compatible with:
- ArcGIS Pro 2.x & 3.x (Python 3.x)
- ArcMap 10.1+ (Python 2.7)

Features:
1. Dual-Platform Native Architecture: Automatic session detection for Pro and ArcMap.
2. 3-Tier Intelligent Invert Elevation Engine:
   - Tier 1: Manhole / Node points layer via fast spatial grid hashing.
   - Tier 2: Auto-detection of 25+ standard civil GIS pipe attribute fields.
   - Tier 3: Direct extraction from 3D Polyline Z vertices.
   - Hybrid blending when partial elevation data exists.
3. Hydraulic Engineering QA/QC Metrics:
   - START_INV, END_INV, INVERT_DROP (m)
   - PIPE_LEN (m), SLOPE_PCT (%), SLOPE_PER_MIL (‰)
   - QA_FLOW_STATUS, QA_SEVERITY (NORMAL_DOWNHILL, ADVERSE_SLOPE, ZERO_SLOPE, etc.)
4. Centroid Midpoint Alignment: Offsets triangle centroid so center-of-gravity coincides with line placement.
5. Instantaneous Curve Tangents: Evaluates local derivative along conduit curve.
6. In-Place Polyline Flipping & Attribute Swapping: Corrects adverse digitized slopes in source layer.
7. High-Performance Processing: O(1) spatial grid, progressor integration, O(1) set lookup.

Author: Ahmad Ibrahim
Email: ahmadibrahim.geo@gmail.com
Repository: https://github.com/ahmadibrahim4geo/Create-FlowArrow-Tool.git
License: MIT
"""

from __future__ import print_function, division, absolute_import
import arcpy
import math
import os
import time

# ---------------------------------------------------------------------------
# Industry Standard Invert Elevation Field Synonyms
# ---------------------------------------------------------------------------

START_INVERT_SYNONYMS = {
    "ST_INV_M", "START_INV", "US_INVERT", "UPSTREAM_IL", "INV_IN",
    "START_INVERT", "US_INV", "UP_INV", "INVERT_START", "INVERT_1",
    "IL_START", "US_IL", "INVERT_UP", "FROM_INVERT", "FROM_IL",
    "START_ELEV", "UPSTREAM_ELEV", "INVERT_US", "US_ELEV", "INV_START",
    "US_INVERT_ELEV", "START_INVERT_ELEV", "INVERTIN"
}

END_INVERT_SYNONYMS = {
    "END_INV_M", "END_INV", "DS_INVERT", "DOWNSTREAM_IL", "INV_OUT",
    "END_INVERT", "DS_INV", "DN_INV", "INVERT_END", "INVERT_2",
    "IL_END", "DS_IL", "INVERT_DN", "TO_INVERT", "TO_IL",
    "END_ELEV", "DOWNSTREAM_ELEV", "INVERT_DS", "DS_ELEV", "INV_END",
    "DS_INVERT_ELEV", "END_INVERT_ELEV", "INVERTOUT"
}


class Toolbox(object):
    def __init__(self):
        """Define the toolbox."""
        self.label = "Flow Direction Arrow Toolbox"
        self.alias = "FlowArrowToolbox"
        self.tools = [CreateFlowArrow]


class CreateFlowArrow(object):
    def __init__(self):
        """Define the tool."""
        self.label = "Create Flow Direction Arrows"
        self.description = (
            "Generates flow direction arrow features (Polygon or Polyline) aligned with "
            "pipe digitization direction (Start Node to End Node) or driven by node invert elevations "
            "for gravity networks (stormwater, sewer, groundwater lowering), with automated QA/QC slope auditing "
            "and optional in-place line flipping."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions."""

        # 0. Input Pipes Layer
        param0 = arcpy.Parameter(
            displayName="Input Pipe Lines",
            name="input_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )
        param0.filter.list = ["Polyline"]

        # 1. Output Workspace / Geodatabase
        param1 = arcpy.Parameter(
            displayName="Output Geodatabase or Workspace",
            name="output_workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input"
        )

        # 2. Output Layer Name
        param2 = arcpy.Parameter(
            displayName="Output Layer Name",
            name="output_layer_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        param2.value = "Flow_Direction_Arrows"

        # 3. Output Geometry Type (Polygon or Polyline)
        param3 = arcpy.Parameter(
            displayName="Output Geometry Type",
            name="geometry_type",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        param3.filter.list = ["Polygon", "Polyline"]
        param3.value = "Polygon"

        # 4. Arrow Base Width
        param4 = arcpy.Parameter(
            displayName="Arrow Base Width (Meters)",
            name="triangle_base",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input"
        )
        param4.value = 2.0

        # 5. Arrow Height / Length
        param5 = arcpy.Parameter(
            displayName="Arrow Height / Length (Meters)",
            name="triangle_height",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input"
        )
        param5.value = 5.0

        # 6. Transfer Pipe Attributes
        param6 = arcpy.Parameter(
            displayName="Transfer Pipe Attributes",
            name="transfer_attributes",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        param6.value = True

        # 7. Optional Node/Manhole Points Layer
        param7 = arcpy.Parameter(
            displayName="Optional Node/Manhole Points Layer",
            name="point_layer",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input"
        )
        param7.filter.list = ["Point", "Multipoint"]

        # 8. Node Invert Elevation Field
        param8 = arcpy.Parameter(
            displayName="Node Invert Elevation Field",
            name="invert_field",
            datatype="Field",
            parameterType="Optional",
            direction="Input"
        )
        param8.parameterDependencies = [param7.name]
        param8.enabled = False

        # 9. Auto-Flip Reversed Pipe Lines
        param9 = arcpy.Parameter(
            displayName="Auto-Flip Reversed Pipe Lines (In-Place)",
            name="flip_reversed_pipes",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        param9.value = False

        # 10. Node Snapping Tolerance (Meters)
        param10 = arcpy.Parameter(
            displayName="Node Snapping Tolerance (Meters)",
            name="search_tolerance",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input"
        )
        param10.value = 1.5
        param10.enabled = False

        # 11. Arrow Placement Along Pipe
        param11 = arcpy.Parameter(
            displayName="Arrow Placement Along Pipe",
            name="arrow_placement",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )
        param11.filter.list = ["Midpoint (50%)", "Quarter (25%)", "Three-Quarters (75%)"]
        param11.value = "Midpoint (50%)"

        # 12. Swap Invert Attributes on Flip
        param12 = arcpy.Parameter(
            displayName="Swap Invert Attributes on Flipped Pipes",
            name="swap_invert_fields",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        param12.value = True
        param12.enabled = False

        # 13. Derived Output (For auto-adding to active map & ModelBuilder)
        param13 = arcpy.Parameter(
            displayName="Output Flow Arrows Layer",
            name="output_feature_class",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output"
        )
        param13.parameterDependencies = [param1.name]

        return [
            param0, param1, param2, param3, param4, param5, param6,
            param7, param8, param9, param10, param11, param12, param13
        ]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation."""
        # Enable/disable node invert options based on point_layer
        if parameters[7].value:
            parameters[8].enabled = True
            parameters[10].enabled = True
        else:
            parameters[8].enabled = False
            parameters[10].enabled = False
            parameters[8].value = None

        # Enable/disable invert swap based on auto-flip
        if parameters[9].value:
            parameters[12].enabled = True
        else:
            parameters[12].enabled = False

    def updateMessages(self, parameters):
        """Modify messages created by internal validation."""
        if parameters[7].value and not parameters[8].value:
            parameters[8].setWarningMessage("Please select an Invert Elevation field from the node points layer.")
        if parameters[4].value and parameters[4].value <= 0:
            parameters[4].setErrorMessage("Arrow Base Width must be greater than zero.")
        if parameters[5].value and parameters[5].value <= 0:
            parameters[5].setErrorMessage("Arrow Height must be greater than zero.")
        if parameters[10].value and parameters[10].value <= 0:
            parameters[10].setErrorMessage("Search tolerance must be greater than zero.")

    def execute(self, parameters, messages):
        """Execute the tool."""
        t_start = time.time()

        input_layer = parameters[0].valueAsText
        output_workspace = parameters[1].valueAsText
        output_layer_name = parameters[2].valueAsText
        geom_type = parameters[3].valueAsText or "Polygon"
        triangle_base = float(parameters[4].value)
        triangle_height = float(parameters[5].value)
        transfer_attributes = bool(parameters[6].value)
        
        point_layer = parameters[7].valueAsText if parameters[7].value else None
        invert_field = parameters[8].valueAsText if parameters[8].value else None
        flip_reversed_pipes = bool(parameters[9].value) if parameters[9].value else False
        search_tolerance = float(parameters[10].value) if parameters[10].value else 1.5
        arrow_placement = parameters[11].valueAsText or "Midpoint (50%)"
        swap_invert_fields = bool(parameters[12].value) if parameters[12].value is not None else True

        # Validate workspaces
        if not arcpy.Exists(output_workspace):
            arcpy.AddError("Specified output workspace does not exist: {}".format(output_workspace))
            return

        if not arcpy.Exists(input_layer):
            arcpy.AddError("Input pipe layer does not exist: {}".format(input_layer))
            return

        output_layer = os.path.join(output_workspace, output_layer_name)

        if arcpy.Exists(output_layer):
            try:
                arcpy.Delete_management(output_layer)
                arcpy.AddMessage("Overwriting existing layer: {}".format(output_layer_name))
            except Exception:
                pass

        # Extract spatial reference
        desc = arcpy.Describe(input_layer)
        spatial_ref = desc.spatialReference
        sr_name = spatial_ref.name if spatial_ref else "Unknown"
        is_has_z = getattr(desc, "hasZ", False)
        arcpy.AddMessage("Spatial Reference: {} (Z-Aware: {})".format(sr_name, is_has_z))

        # Parse placement ratio
        placement_ratio = 0.5
        if "25" in arrow_placement or "Quarter" in arrow_placement:
            placement_ratio = 0.25
        elif "75" in arrow_placement or "Three-Quarters" in arrow_placement:
            placement_ratio = 0.75

        # Tier 1: Build spatial index for Node Points if provided
        point_grid = {}
        search_tol = max(0.05, search_tolerance)
        cell_size = max(search_tol, 1.0)
        use_node_inverts = False
        node_point_count = 0

        if point_layer and invert_field and arcpy.Exists(point_layer):
            arcpy.AddMessage("Loading node points and building spatial index from: {} (Tolerance: {}m)...".format(point_layer, search_tol))
            try:
                with arcpy.da.SearchCursor(point_layer, ["SHAPE@X", "SHAPE@Y", invert_field], spatial_reference=spatial_ref) as pt_cur:
                    for px, py, inv_val in pt_cur:
                        if px is not None and py is not None and inv_val is not None:
                            try:
                                inv_num = float(inv_val)
                                cx = int(math.floor(px / cell_size))
                                cy = int(math.floor(py / cell_size))
                                key = (cx, cy)
                                if key not in point_grid:
                                    point_grid[key] = []
                                point_grid[key].append((px, py, inv_num))
                                node_point_count += 1
                            except (ValueError, TypeError):
                                pass
                arcpy.AddMessage("Successfully indexed {} node points with valid invert elevations.".format(node_point_count))
                use_node_inverts = True if node_point_count > 0 else False
            except Exception as e_pt:
                arcpy.AddWarning("Could not process node points layer: {}. Falling back to line attributes/3D geometry.".format(e_pt))

        def get_nearest_invert(px, py, max_dist=search_tol):
            if not point_grid:
                return None
            cx = int(math.floor(px / cell_size))
            cy = int(math.floor(py / cell_size))
            r_cells = int(math.ceil(max_dist / cell_size))
            best_dist_sq = max_dist * max_dist
            best_inv = None
            for dx in range(-r_cells, r_cells + 1):
                for dy in range(-r_cells, r_cells + 1):
                    cell = (cx + dx, cy + dy)
                    if cell in point_grid:
                        for (x, y, inv) in point_grid[cell]:
                            d_sq = (x - px) ** 2 + (y - py) ** 2
                            if d_sq <= best_dist_sq:
                                best_dist_sq = d_sq
                                best_inv = inv
            return best_inv

        # Target feature class geometry
        fc_geom_type = "POLYGON" if geom_type.lower() == "polygon" else "POLYLINE"

        arcpy.CreateFeatureclass_management(
            out_path=output_workspace,
            out_name=output_layer_name,
            geometry_type=fc_geom_type,
            spatial_reference=spatial_ref
        )
        arcpy.AddMessage("Created output {} feature class: {}".format(fc_geom_type, output_layer_name))

        # Add engineering tracking & QA/QC fields
        arcpy.AddField_management(output_layer, "ORIG_FID", "LONG", field_alias="Original Pipe FID")
        arcpy.AddField_management(output_layer, "QA_FLOW_STATUS", "TEXT", field_length=100, field_alias="Flow QA/QC Status")
        arcpy.AddField_management(output_layer, "QA_SEVERITY", "TEXT", field_length=30, field_alias="QA Severity Code")
        arcpy.AddField_management(output_layer, "INVERT_SRC", "TEXT", field_length=30, field_alias="Invert Data Source")
        arcpy.AddField_management(output_layer, "START_INV", "DOUBLE", field_alias="Start Invert Elevation (m)")
        arcpy.AddField_management(output_layer, "END_INV", "DOUBLE", field_alias="End Invert Elevation (m)")
        arcpy.AddField_management(output_layer, "INVERT_DROP", "DOUBLE", field_alias="Invert Drop / Head (m)")
        arcpy.AddField_management(output_layer, "PIPE_LEN", "DOUBLE", field_alias="Pipe Length (m)")
        arcpy.AddField_management(output_layer, "SLOPE_PCT", "DOUBLE", field_alias="Hydraulic Slope (%)")
        arcpy.AddField_management(output_layer, "SLOPE_PER_MIL", "DOUBLE", field_alias="Hydraulic Slope (per mil)")
        arcpy.AddField_management(output_layer, "FLIPPED", "TEXT", field_length=10, field_alias="Flipped In-Place")

        # Tier 2: Inspect fields for pipe invert elevation detection
        input_fields = [f.name for f in arcpy.ListFields(input_layer)]
        input_field_objs = {f.name: f for f in arcpy.ListFields(input_layer)}

        st_inv_line_field = None
        end_inv_line_field = None
        for f in input_fields:
            f_upper = f.upper()
            if f_upper in START_INVERT_SYNONYMS and not st_inv_line_field:
                st_inv_line_field = f
            elif f_upper in END_INVERT_SYNONYMS and not end_inv_line_field:
                end_inv_line_field = f

        if st_inv_line_field and end_inv_line_field:
            arcpy.AddMessage("Auto-detected Pipe Invert Fields: Start='{}', End='{}'".format(st_inv_line_field, end_inv_line_field))

        # Attributes transfer setup
        fields_to_copy = []
        managed_fields = {
            "ORIG_FID", "QA_FLOW_STATUS", "QA_SEVERITY", "INVERT_SRC",
            "START_INV", "END_INV", "INVERT_DROP", "PIPE_LEN",
            "SLOPE_PCT", "SLOPE_PER_MIL", "FLIPPED"
        }

        if transfer_attributes:
            for f in input_fields:
                f_obj = input_field_objs[f]
                if f_obj.type in ("OID", "Geometry") or f.upper().startswith("SHAPE"):
                    continue
                if f.upper() in managed_fields:
                    continue
                try:
                    arcpy.AddField_management(
                        output_layer, f_obj.name, f_obj.type,
                        field_precision=f_obj.precision,
                        field_scale=f_obj.scale,
                        field_length=f_obj.length,
                        field_alias=f_obj.aliasName
                    )
                    fields_to_copy.append(f)
                except Exception:
                    pass

        search_fields = ["SHAPE@", "OID@"] + fields_to_copy
        insert_fields = [
            "SHAPE@", "ORIG_FID", "QA_FLOW_STATUS", "QA_SEVERITY", "INVERT_SRC",
            "START_INV", "END_INV", "INVERT_DROP", "PIPE_LEN",
            "SLOPE_PCT", "SLOPE_PER_MIL", "FLIPPED"
        ] + fields_to_copy

        st_attr_idx = fields_to_copy.index(st_inv_line_field) if st_inv_line_field and st_inv_line_field in fields_to_copy else None
        end_attr_idx = fields_to_copy.index(end_inv_line_field) if end_inv_line_field and end_inv_line_field in fields_to_copy else None

        # Statistics
        total_pipes = 0
        normal_count = 0
        reversed_count = 0
        flat_count = 0
        partial_count = 0
        digitized_only_count = 0
        src_node_count = 0
        src_attr_count = 0
        src_3d_count = 0
        reversed_pipe_oids = []

        try:
            count_res = arcpy.GetCount_management(input_layer)
            total_features_est = int(count_res.getOutput(0))
            arcpy.SetProgressor("step", "Processing flow arrows...", 0, total_features_est, 1)
        except Exception:
            total_features_est = 0

        with arcpy.da.SearchCursor(input_layer, search_fields) as cursor:
            with arcpy.da.InsertCursor(output_layer, insert_fields) as insert_cursor:
                for row in cursor:
                    total_pipes += 1
                    if total_features_est > 0 and total_pipes % 50 == 0:
                        try:
                            arcpy.SetProgressorPosition(total_pipes)
                        except Exception:
                            pass

                    line = row[0]
                    orig_fid = row[1]
                    attr_values = list(row[2:])

                    if not line or line.length <= 1e-4:
                        continue

                    pipe_len = round(float(line.length), 3)
                    start_point = line.firstPoint
                    end_point = line.lastPoint

                    # Calculate local tangent angle along curve at anchor placement
                    try:
                        pct_anchor = placement_ratio
                        pct_before = max(0.01, pct_anchor - 0.01)
                        pct_after = min(0.99, pct_anchor + 0.01)
                        anchor_pt = line.positionAlongLine(pct_anchor, True).firstPoint
                        p_before = line.positionAlongLine(pct_before, True).firstPoint
                        p_after = line.positionAlongLine(pct_after, True).firstPoint
                        dx = p_after.X - p_before.X
                        dy = p_after.Y - p_before.Y
                        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                            raise ValueError()
                    except Exception:
                        anchor_pt = line.positionAlongLine(placement_ratio, True).firstPoint
                        dx = end_point.X - start_point.X
                        dy = end_point.Y - start_point.Y

                    digitized_angle = math.atan2(dy, dx)

                    # -------------------------------------------------------
                    # 3-Tier Intelligent Invert Evaluation
                    # -------------------------------------------------------
                    st_inv = None
                    end_inv = None
                    inv_src = "DIGITIZED_ONLY"

                    # Tier 1: Connected Node Points
                    if use_node_inverts:
                        st_inv = get_nearest_invert(start_point.X, start_point.Y)
                        end_inv = get_nearest_invert(end_point.X, end_point.Y)
                        if st_inv is not None and end_inv is not None:
                            inv_src = "NODES_LAYER"
                        elif st_inv is not None or end_inv is not None:
                            inv_src = "HYBRID_NODES"

                    # Tier 2: Pipe Line Attributes
                    if (st_inv is None or end_inv is None) and (st_attr_idx is not None and end_attr_idx is not None):
                        try:
                            if st_inv is None and attr_values[st_attr_idx] is not None:
                                st_inv = float(attr_values[st_attr_idx])
                            if end_inv is None and attr_values[end_attr_idx] is not None:
                                end_inv = float(attr_values[end_attr_idx])
                            if inv_src == "DIGITIZED_ONLY" and st_inv is not None and end_inv is not None:
                                inv_src = "PIPE_ATTRIBUTES"
                        except (ValueError, TypeError):
                            pass

                    # Tier 3: 3D Geometry Vertices
                    if (st_inv is None or end_inv is None) and is_has_z:
                        try:
                            z_start = getattr(start_point, "Z", None)
                            z_end = getattr(end_point, "Z", None)
                            if z_start is not None and not math.isnan(z_start) and (z_start > -9000):
                                if st_inv is None:
                                    st_inv = float(z_start)
                            if z_end is not None and not math.isnan(z_end) and (z_end > -9000):
                                if end_inv is None:
                                    end_inv = float(z_end)
                            if inv_src == "DIGITIZED_ONLY" and st_inv is not None and end_inv is not None:
                                inv_src = "3D_GEOMETRY"
                        except Exception:
                            pass

                    if inv_src == "NODES_LAYER":
                        src_node_count += 1
                    elif inv_src == "PIPE_ATTRIBUTES":
                        src_attr_count += 1
                    elif inv_src == "3D_GEOMETRY":
                        src_3d_count += 1

                    # Hydraulic evaluation
                    inv_drop = None
                    slope_pct = None
                    slope_per_mil = None
                    is_reversed = False
                    qa_severity = "UNKNOWN"
                    qa_status = "Normal Flow (Digitized Direction - No Inverts)"

                    if st_inv is not None and end_inv is not None:
                        st_inv = round(st_inv, 4)
                        end_inv = round(end_inv, 4)
                        inv_drop = round(st_inv - end_inv, 4)
                        if pipe_len > 0:
                            slope_pct = round((inv_drop / pipe_len) * 100.0, 4)
                            slope_per_mil = round((inv_drop / pipe_len) * 1000.0, 3)

                        if st_inv > end_inv:
                            qa_severity = "NORMAL_DOWNHILL"
                            qa_status = "Normal Flow (Downhill: Drop={:+.3f}m, Slope={:.2f}%)".format(inv_drop, slope_pct or 0.0)
                            normal_count += 1
                        elif st_inv < end_inv:
                            is_reversed = True
                            qa_severity = "ADVERSE_SLOPE"
                            qa_status = "REVERSED - Flow Corrected by Inverts (Adverse Drop={:+.3f}m)".format(inv_drop)
                            reversed_count += 1
                            reversed_pipe_oids.append(orig_fid)
                        else:
                            qa_severity = "ZERO_SLOPE"
                            qa_status = "Flat Pipe (Zero Invert Drop / Horizontal conduit)"
                            flat_count += 1
                    elif st_inv is not None or end_inv is not None:
                        qa_severity = "PARTIAL_ELEVATION"
                        qa_status = "Partial Invert (Single Node/Elevation Found)"
                        partial_count += 1
                    else:
                        qa_severity = "DIGITIZED_ONLY"
                        qa_status = "Digitized Direction (No Invert Elevations Found)"
                        digitized_only_count += 1

                    # Set arrow angle: If reversed, flip 180 degrees to point downhill
                    if is_reversed:
                        arrow_angle = digitized_angle + math.pi
                        if arrow_angle > math.pi:
                            arrow_angle -= 2.0 * math.pi
                    else:
                        arrow_angle = digitized_angle

                    # Arrow geometry vertices relative to anchor point
                    base_left = arcpy.Point(
                        anchor_pt.X - (triangle_base / 2.0) * math.sin(arrow_angle),
                        anchor_pt.Y + (triangle_base / 2.0) * math.cos(arrow_angle)
                    )
                    base_right = arcpy.Point(
                        anchor_pt.X + (triangle_base / 2.0) * math.sin(arrow_angle),
                        anchor_pt.Y - (triangle_base / 2.0) * math.cos(arrow_angle)
                    )
                    tip = arcpy.Point(
                        anchor_pt.X + triangle_height * math.cos(arrow_angle),
                        anchor_pt.Y + triangle_height * math.sin(arrow_angle)
                    )

                    # Centroid offset: shift so triangle centroid aligns with anchor point
                    mid_tri_x = (base_left.X + base_right.X + tip.X) / 3.0
                    mid_tri_y = (base_left.Y + base_right.Y + tip.Y) / 3.0

                    off_x = anchor_pt.X - mid_tri_x
                    off_y = anchor_pt.Y - mid_tri_y

                    base_left_adj = arcpy.Point(base_left.X + off_x, base_left.Y + off_y)
                    base_right_adj = arcpy.Point(base_right.X + off_x, base_right.Y + off_y)
                    tip_adj = arcpy.Point(tip.X + off_x, tip.Y + off_y)

                    if fc_geom_type == "POLYGON":
                        arrow_geom = arcpy.Polygon(
                            arcpy.Array([base_left_adj, base_right_adj, tip_adj, base_left_adj]),
                            spatial_ref
                        )
                    else:
                        arrow_geom = arcpy.Polyline(
                            arcpy.Array([base_left_adj, tip_adj, base_right_adj]),
                            spatial_ref
                        )

                    flipped_flag = "YES" if (flip_reversed_pipes and is_reversed) else "NO"
                    insert_row = [
                        arrow_geom, orig_fid, qa_status, qa_severity, inv_src,
                        st_inv, end_inv, inv_drop, pipe_len,
                        slope_pct, slope_per_mil, flipped_flag
                    ] + attr_values
                    insert_cursor.insertRow(insert_row)

        try:
            arcpy.ResetProgressor()
        except Exception:
            pass

        # In-Place Pipe Line Geometry Flipping & Attribute Swapping
        flipped_count = 0
        if flip_reversed_pipes and reversed_pipe_oids:
            reversed_oids_set = set(reversed_pipe_oids)
            arcpy.AddMessage("Auto-flipping {} reversed pipe line(s) in-place to follow gravity flow...".format(len(reversed_oids_set)))

            update_fields = ["OID@", "SHAPE@"]
            s_up_idx = None
            e_up_idx = None
            if swap_invert_fields and st_inv_line_field and end_inv_line_field:
                update_fields.extend([st_inv_line_field, end_inv_line_field])
                s_up_idx = 2
                e_up_idx = 3

            try:
                with arcpy.da.UpdateCursor(input_layer, update_fields) as up_cursor:
                    for up_row in up_cursor:
                        oid = up_row[0]
                        if oid in reversed_oids_set:
                            cur_line = up_row[1]
                            if cur_line:
                                parts = arcpy.Array()
                                for part in reversed(cur_line):
                                    rev_pts = arcpy.Array(list(reversed([p for p in part if p])))
                                    parts.add(rev_pts)
                                up_row[1] = arcpy.Polyline(parts, spatial_ref)

                                # Swap start and end invert attributes on the pipe feature
                                if s_up_idx is not None and e_up_idx is not None:
                                    old_st = up_row[s_up_idx]
                                    old_end = up_row[e_up_idx]
                                    up_row[s_up_idx] = old_end
                                    up_row[e_up_idx] = old_st

                                up_cursor.updateRow(up_row)
                                flipped_count += 1
                arcpy.AddMessage("Successfully flipped {} pipe line(s) in the input layer.".format(flipped_count))
            except Exception as ex_flip:
                arcpy.AddWarning("Could not flip pipe lines in-place (layer may be locked or read-only): {}".format(ex_flip))

        # Professional Engineering Summary Output
        elapsed = round(time.time() - t_start, 2)
        pct_norm = (normal_count / total_pipes * 100.0) if total_pipes else 0.0
        pct_rev = (reversed_count / total_pipes * 100.0) if total_pipes else 0.0
        pct_flat = (flat_count / total_pipes * 100.0) if total_pipes else 0.0

        summary_banner = """
======================================================================
  🌊 CREATE FLOW ARROW & QA/QC AUDIT ENGINE - SUMMARY
======================================================================
  Total Pipes Analyzed:          {}
  - Normal Downhill Flow:        {} ({:.1f}%)
  - Adverse Slope (Reversed):    {} ({:.1f}%)
  - Flat Pipes (Zero Drop):      {} ({:.1f}%)
  - Partial Inverts / Unlinked:  {}
  - Digitized Direction Only:    {}
  ------------------------------------------------------------------
  Invert Elevation Sources:
  - Node Manhole Points:         {}
  - Pipe Attribute Fields:       {}
  - 3D Geometry Vertices:        {}
  ------------------------------------------------------------------
  In-Place Auto-Flip Executed:   {} pipe(s) corrected
  Output Feature Class:          {}
  Elapsed Execution Time:        {} seconds
======================================================================
""".format(
            total_pipes,
            normal_count, pct_norm,
            reversed_count, pct_rev,
            flat_count, pct_flat,
            partial_count,
            digitized_only_count,
            src_node_count,
            src_attr_count,
            src_3d_count,
            flipped_count,
            output_layer,
            elapsed
        )

        arcpy.AddMessage(summary_banner)
        if reversed_count > 0 and not flip_reversed_pipes:
            arcpy.AddWarning(
                "QA/QC Alert: Identified {} pipe(s) with adverse/reversed slope. Arrows oriented downhill. Enable 'Auto-Flip' to correct in-place.".format(reversed_count)
            )

        # Pass output to derived parameter
        parameters[13].value = output_layer

        # Auto-add to active map session
        self._add_to_active_map(output_layer)

    def _add_to_active_map(self, layer_path):
        """Add output layer to the active map session (ArcGIS Pro or ArcMap)."""
        if hasattr(arcpy, "mp"):
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                active_map = aprx.activeMap or (aprx.listMaps()[0] if aprx.listMaps() else None)
                if active_map:
                    active_map.addDataFromPath(layer_path)
                    arcpy.AddMessage("(ArcGIS Pro): Layer added to active map successfully.")
                    return True
            except Exception:
                return False

        elif hasattr(arcpy, "mapping"):
            try:
                mxd = arcpy.mapping.MapDocument("CURRENT")
                df = arcpy.mapping.ListDataFrames(mxd)[0]
                new_layer = arcpy.mapping.Layer(layer_path)
                arcpy.mapping.AddLayer(df, new_layer)
                arcpy.RefreshTOC()
                arcpy.RefreshActiveView()
                arcpy.AddMessage("(ArcMap): Layer added to active data frame successfully.")
                return True
            except Exception:
                return False

        return False
