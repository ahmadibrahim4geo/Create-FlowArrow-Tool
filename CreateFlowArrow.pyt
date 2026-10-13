# -*- coding: utf-8 -*-
"""
CreateFlowArrow.pyt
-------------------
Unified ArcGIS Python Toolbox for generating flow direction arrows on gravity infrastructure networks.
Fully compatible with ArcGIS Pro (Python 3.x) and ArcMap 10.1+ (Python 2.7).

New Feature:
- Optional Node/Manhole Points Layer with Invert Elevation comparison (Z_higher -> Z_lower).
- Downhill arrow orientation based on actual invert elevations.
- Auto-Flip reversed pipe lines in-place to correct digitized direction.

Author: Ahmad Ibrahim
Email: ahmadibrahim.geo@gmail.com
Repository: https://github.com/ahmadibrahim4geo/Create-FlowArrow-Tool.git
License: MIT
"""

from __future__ import print_function, division, absolute_import
import arcpy
import math
import os


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
            "for gravity networks (stormwater, sewer, groundwater lowering), with automated QA/QC auditing "
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
        param9.enabled = False

        # 10. Derived Output (For auto-adding to active map)
        param10 = arcpy.Parameter(
            displayName="Output Flow Arrows Layer",
            name="output_feature_class",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output"
        )
        param10.parameterDependencies = [param1.name]

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8, param9, param10]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation."""
        # Enable or disable invert field (param 8) and auto-flip (param 9) based on point_layer (param 7)
        if parameters[7].value:
            parameters[8].enabled = True
            parameters[9].enabled = True
        else:
            parameters[8].enabled = False
            parameters[9].enabled = False
            parameters[8].value = None
            parameters[9].value = False

    def updateMessages(self, parameters):
        """Modify messages created by internal validation."""
        if parameters[7].value and not parameters[8].value:
            parameters[8].setWarningMessage("Please select an Invert Elevation field from the node points layer.")

    def execute(self, parameters, messages):
        """Execute the tool."""
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

        # Validate output workspace
        if not arcpy.Exists(output_workspace):
            arcpy.AddError("Specified output workspace does not exist: {}".format(output_workspace))
            return

        # Validate input layer
        if not arcpy.Exists(input_layer):
            arcpy.AddError("Input pipe layer does not exist: {}".format(input_layer))
            return

        output_layer = os.path.join(output_workspace, output_layer_name)

        # Remove existing layer if present
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
        arcpy.AddMessage("Spatial Reference: {}".format(sr_name))

        # Build spatial index for Node Points if provided
        point_grid = {}
        cell_size = 2.0  # meter grid cell
        use_node_inverts = False

        if point_layer and invert_field and arcpy.Exists(point_layer):
            arcpy.AddMessage("Loading node points and building spatial index from: {}...".format(point_layer))
            point_count = 0
            try:
                with arcpy.da.SearchCursor(point_layer, ["SHAPE@XY", invert_field], spatial_reference=spatial_ref) as pt_cur:
                    for pt_row in pt_cur:
                        xy = pt_row[0]
                        inv_val = pt_row[1]
                        if xy and inv_val is not None:
                            try:
                                inv_num = float(inv_val)
                                cx = int(math.floor(xy[0] / cell_size))
                                cy = int(math.floor(xy[1] / cell_size))
                                key = (cx, cy)
                                if key not in point_grid:
                                    point_grid[key] = []
                                point_grid[key].append((xy[0], xy[1], inv_num))
                                point_count += 1
                            except (ValueError, TypeError):
                                pass
                arcpy.AddMessage("Successfully indexed {} node points with valid invert elevations.".format(point_count))
                use_node_inverts = True if point_count > 0 else False
            except Exception as e_pt:
                arcpy.AddWarning("Could not process node points layer: {}. Falling back to line attributes.".format(e_pt))

        def get_nearest_invert(px, py, max_dist=1.5):
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

        # Determine target feature class geometry
        fc_geom_type = "POLYGON" if geom_type.lower() == "polygon" else "POLYLINE"

        # Create output feature class
        arcpy.CreateFeatureclass_management(
            out_path=output_workspace,
            out_name=output_layer_name,
            geometry_type=fc_geom_type,
            spatial_reference=spatial_ref
        )
        arcpy.AddMessage("Created output {} feature class: {}".format(fc_geom_type, output_layer_name))

        # Add tracking & QA/QC fields
        arcpy.AddField_management(output_layer, "ORIG_FID", "LONG", field_alias="Original Pipe FID")
        arcpy.AddField_management(output_layer, "QA_FLOW_STATUS", "TEXT", field_length=50,
                                 field_alias="Flow QA/QC Status")
        arcpy.AddField_management(output_layer, "START_INV", "DOUBLE", field_alias="Start Invert Elevation (m)")
        arcpy.AddField_management(output_layer, "END_INV", "DOUBLE", field_alias="End Invert Elevation (m)")
        arcpy.AddField_management(output_layer, "INVERT_DROP", "DOUBLE", field_alias="Invert Drop / Head (m)")

        # Inspect fields for attribute transfer
        input_fields = [f.name for f in arcpy.ListFields(input_layer)]
        input_field_objs = {f.name: f for f in arcpy.ListFields(input_layer)}

        # Detect pipe line invert elevation fields as secondary check
        st_inv_line_field = None
        end_inv_line_field = None
        for f in input_fields:
            f_upper = f.upper()
            if f_upper in ("ST_INV_M", "START_INV", "US_INVERT", "UPSTREAM_IL", "INV_IN"):
                st_inv_line_field = f
            elif f_upper in ("END_INV_M", "END_INV", "DS_INVERT", "DOWNSTREAM_IL", "INV_OUT"):
                end_inv_line_field = f

        fields_to_copy = []
        if transfer_attributes:
            excluded = ("ORIG_FID", "QA_FLOW_STATUS", "START_INV", "END_INV", "INVERT_DROP")
            for f in input_fields:
                f_obj = input_field_objs[f]
                if f_obj.type in ("OID", "Geometry") or f.upper().startswith("SHAPE"):
                    continue
                if f.upper() in excluded:
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
        insert_fields = ["SHAPE@", "ORIG_FID", "QA_FLOW_STATUS", "START_INV", "END_INV", "INVERT_DROP"] + fields_to_copy

        feature_count = 0
        reversed_count = 0
        reversed_pipe_oids = []

        with arcpy.da.SearchCursor(input_layer, search_fields) as cursor:
            with arcpy.da.InsertCursor(output_layer, insert_fields) as insert_cursor:
                for row in cursor:
                    line = row[0]
                    orig_fid = row[1]
                    attr_values = list(row[2:])

                    if not line or line.length == 0:
                        continue

                    start_point = line.firstPoint
                    end_point = line.lastPoint
                    mid_point = line.positionAlongLine(0.5, True).firstPoint

                    # Calculate local tangent angle at 50% midpoint
                    try:
                        p_before = line.positionAlongLine(0.49, True).firstPoint
                        p_after = line.positionAlongLine(0.51, True).firstPoint
                        dx = p_after.X - p_before.X
                        dy = p_after.Y - p_before.Y
                        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                            raise ValueError()
                    except Exception:
                        dx = end_point.X - start_point.X
                        dy = end_point.Y - start_point.Y

                    digitized_angle = math.atan2(dy, dx)

                    # Invert Evaluation: Higher Invert flows to Lower Invert
                    st_inv = None
                    end_inv = None
                    inv_drop = None
                    is_reversed = False
                    qa_status = "Normal Flow (Digitized Direction)"

                    if use_node_inverts:
                        st_inv = get_nearest_invert(start_point.X, start_point.Y)
                        end_inv = get_nearest_invert(end_point.X, end_point.Y)
                    elif st_inv_line_field and end_inv_line_field:
                        try:
                            s_idx = fields_to_copy.index(st_inv_line_field)
                            e_idx = fields_to_copy.index(end_inv_line_field)
                            if attr_values[s_idx] is not None and attr_values[e_idx] is not None:
                                st_inv = float(attr_values[s_idx])
                                end_inv = float(attr_values[e_idx])
                        except Exception:
                            pass

                    if st_inv is not None and end_inv is not None:
                        inv_drop = round(st_inv - end_inv, 4)
                        if st_inv > end_inv:
                            qa_status = "Normal Flow (Downhill)"
                        elif st_inv < end_inv:
                            is_reversed = True
                            qa_status = "REVERSED - Flow Corrected by Inverts"
                            reversed_count += 1
                            reversed_pipe_oids.append(orig_fid)
                        else:
                            qa_status = "Flat Pipe (Zero Invert Drop)"
                    elif st_inv is not None or end_inv is not None:
                        qa_status = "Partial Invert (Single Node Found)"

                    # Set arrow angle: If reversed, flip 180 degrees to point downhill
                    if is_reversed:
                        arrow_angle = digitized_angle + math.pi
                        if arrow_angle > math.pi:
                            arrow_angle -= 2.0 * math.pi
                    else:
                        arrow_angle = digitized_angle

                    # Arrow geometry vertices relative to midpoint
                    base_left = arcpy.Point(
                        mid_point.X - (triangle_base / 2.0) * math.sin(arrow_angle),
                        mid_point.Y + (triangle_base / 2.0) * math.cos(arrow_angle)
                    )
                    base_right = arcpy.Point(
                        mid_point.X + (triangle_base / 2.0) * math.sin(arrow_angle),
                        mid_point.Y - (triangle_base / 2.0) * math.cos(arrow_angle)
                    )
                    tip = arcpy.Point(
                        mid_point.X + triangle_height * math.cos(arrow_angle),
                        mid_point.Y + triangle_height * math.sin(arrow_angle)
                    )

                    # Centroid offset: shift so triangle centroid aligns with line midpoint
                    mid_tri_x = (base_left.X + base_right.X + tip.X) / 3.0
                    mid_tri_y = (base_left.Y + base_right.Y + tip.Y) / 3.0

                    off_x = mid_point.X - mid_tri_x
                    off_y = mid_point.Y - mid_tri_y

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

                    insert_row = [arrow_geom, orig_fid, qa_status, st_inv, end_inv, inv_drop] + attr_values
                    insert_cursor.insertRow(insert_row)
                    feature_count += 1

        arcpy.AddMessage("Successfully generated {} flow direction arrows ({}).".format(feature_count, fc_geom_type))

        if reversed_count > 0:
            arcpy.AddWarning(
                "QA/QC Alert: Identified {} pipe(s) with adverse/reversed slope. Arrows have been oriented downhill.".format(reversed_count)
            )

        # In-Place Pipe Line Geometry Flipping (if requested)
        if flip_reversed_pipes and reversed_pipe_oids:
            arcpy.AddMessage("Auto-flipping {} reversed pipe line(s) in-place to follow gravity flow...".format(len(reversed_pipe_oids)))
            flipped_count = 0
            try:
                with arcpy.da.UpdateCursor(input_layer, ["OID@", "SHAPE@"]) as up_cursor:
                    for up_row in up_cursor:
                        if up_row[0] in reversed_pipe_oids:
                            cur_line = up_row[1]
                            if cur_line:
                                parts = arcpy.Array()
                                for part in cur_line:
                                    rev_pts = arcpy.Array(list(reversed([p for p in part if p])))
                                    parts.add(rev_pts)
                                up_row[1] = arcpy.Polyline(parts, spatial_ref)
                                up_cursor.updateRow(up_row)
                                flipped_count += 1
                arcpy.AddMessage("Successfully flipped {} pipe line(s) in the input layer.".format(flipped_count))
            except Exception as ex_flip:
                arcpy.AddWarning("Could not flip pipe lines in-place (layer may be locked or read-only): {}".format(ex_flip))

        # Pass output to derived parameter
        parameters[10].value = output_layer

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
