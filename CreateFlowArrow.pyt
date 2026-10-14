# -*- coding: utf-8 -*-
"""
CreateFlowArrow.pyt
-------------------
Unified ArcGIS Python Toolbox for generating flow direction arrows and
conducting automated QA/QC slope & flow direction audits on gravity infrastructure networks.

Fully compatible with:
- ArcGIS Pro 2.x & 3.x (Python 3.x)
- ArcMap 10.1+ (Python 2.7)
- Arabic and International File Paths, Geodatabases, Layer Names, and Field Data

Features:
1. Dual-Platform Native Architecture: Automatic session detection for Pro and ArcMap.
2. Full Arabic Language Support:
   - Robust Unicode encoding/decoding across Windows file paths, Arabic folder names,
     Arabic Geodatabases (.gdb), Arabic layer names, and Arabic attribute fields/aliases.
   - Safe logging that prevents console codepage crashes in English and Arabic locales.
3. Smart Node Invert & Hydraulic Slope Engine:
   - Activated strictly when the user provides the Optional Node Points Layer and Invert Elevation Field.
   - High-speed O(1) spatial grid hashing snaps pipe endpoints to node points.
   - Multi-tier snapping: Exact search tolerance with adaptive soft-snapping fallback.
   - Automatic fallback to pipe-level invert attributes if node points are missing.
   - Comprehensive handling of pipes without start nodes (cul-de-sacs, outfalls, house connections)
     without errors ("تعمل تمام"), generating flow arrows smoothly along digitized direction.
   - Calculates START_INV, END_INV, INVERT_DROP (m), PIPE_LEN (m), SLOPE_PCT (%), and SLOPE_PER_MIL (‰).
   - Downhill arrow orientation based on actual invert elevations (Z_high -> Z_low).
   - Identifies adverse/reversed slope pipes with automated QA/QC status tags.
4. Standard Digitized Mode:
   - When node points are not provided, generates flow direction arrows strictly aligned with digitized direction.
5. Centroid Midpoint Alignment: Offsets triangle centroid so center-of-gravity coincides with line placement.
6. Instantaneous Curve Tangents: Evaluates local derivative along conduit curve.
7. In-Place Polyline Flipping: Corrects adverse digitized slopes in source layer when auto-flip is enabled.
8. High-Performance Processing: O(1) spatial grid, progressor integration, O(1) set lookup.

Author: Ahmad Ibrahim
Email: ahmadibrahim.geo@gmail.com
Repository: https://github.com/ahmadibrahim4geo/Create-FlowArrow-Tool.git
License: MIT
"""

from __future__ import print_function, division, absolute_import
import arcpy
import math
import os
import sys
import time

# ---------------------------------------------------------------------------
# Unicode & String Normalization Helpers (Arabic & International Paths Support)
# ---------------------------------------------------------------------------

def to_unicode(val):
    """Safely convert any object/string to unicode string (Python 2 unicode, Python 3 str)."""
    if val is None:
        return u""
    if sys.version_info[0] >= 3:
        return str(val)
    if isinstance(val, unicode):
        return val
    for enc in ("utf-8", "cp1256", "windows-1256", "iso-8859-6", "latin-1"):
        try:
            return val.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return val.decode("utf-8", "replace")

def to_native_str(val):
    """Convert to native string (str in Python 2 or Python 3)."""
    if val is None:
        return ""
    u_val = to_unicode(val)
    if sys.version_info[0] < 3:
        return u_val.encode("utf-8")
    return u_val

# ---------------------------------------------------------------------------
# Pipe Invert Field Detector (Arabic & English Infrastructure Standards)
# ---------------------------------------------------------------------------

def find_pipe_invert_fields(input_fields):
    """
    Detect start/upstream and end/downstream invert fields on pipe line features.
    Supports Arabic and English industry naming standards (NWC Saudi, Egypt, UAE, international).
    """
    st_patterns = [
        "UPSTREAMINVERT", "UPSTREAMINVERTELEVATION", "UPSTREAMINVERTELEV",
        "UPSTREAM_INVERT", "UPSTREAM_INVERT_ELEVATION", "UPSTREAM_IL",
        "US_INVERT", "US_INV", "US_IL", "US_INVERTELEVATION", "US_ELEV", "US_INV_M",
        "START_INV", "START_INVERT", "START_IL", "START_ELEVATION", "STARTINVERT",
        "ST_INV", "ST_INV_M", "ST_INVERT", "ST_IL",
        "INV_IN", "INVERT_IN", "IN_INVERT", "FROM_INVERT", "FROM_INV", "FROM_IL",
        "INVERT1", "INV1", "IL1", "INVERTA", "INVERT_UP", "IL_UPSTREAM",
        u"منسوب_القاع_البداية", u"منسوب_قاع_البداية", u"منسوب_البداية", u"قاع_البداية",
        u"منسوب_الدخول", u"منسوب_قاع_الدخول", u"قاع_الدخول",
        u"منسوب_القاع_العلوي", u"منسوب_العلوي", u"قاع_علوي", u"المنسوب_العلوي",
        u"منسوب_القاع_1", u"منسوب_1", u"قاع_1", u"منسوب_المدخل"
    ]
    end_patterns = [
        "DOWNSTREAMINVERT", "DOWNSTREAMINVERTELEVATION", "DOWNSTREAMINVERTELEV",
        "DOWNSTREAM_INVERT", "DOWNSTREAM_INVERT_ELEVATION", "DOWNSTREAM_IL",
        "DS_INVERT", "DS_INV", "DS_IL", "DS_INVERTELEVATION", "DS_ELEV", "DS_INV_M",
        "END_INV", "END_INVERT", "END_IL", "END_ELEVATION", "ENDINVERT",
        "END_INV_M", "END_INVERT_M",
        "INV_OUT", "INVERT_OUT", "OUT_INVERT", "TO_INVERT", "TO_INV", "TO_IL",
        "INVERT2", "INV2", "IL2", "INVERTB", "INVERT_DOWN", "IL_DOWNSTREAM",
        u"منسوب_القاع_النهاية", u"منسوب_قاع_النهاية", u"منسوب_النهاية", u"قاع_النهاية",
        u"منسوب_الخروج", u"منسوب_قاع_الخروج", u"قاع_الخروج",
        u"منسوب_القاع_السفلي", u"منسوب_السفلي", u"قاع_سفلي", u"المنسوب_السفلي",
        u"منسوب_القاع_2", u"منسوب_2", u"قاع_2", u"منسوب_المخرج"
    ]

    norm_st = {to_unicode(p).upper().replace(u"_", u"").replace(u" ", u"") for p in st_patterns}
    norm_end = {to_unicode(p).upper().replace(u"_", u"").replace(u" ", u"") for p in end_patterns}

    st_field = None
    end_field = None

    for f in input_fields:
        f_norm = to_unicode(f).upper().replace(u"_", u"").replace(u" ", u"")
        if not st_field and f_norm in norm_st:
            st_field = f
        elif not end_field and f_norm in norm_end:
            end_field = f

    return st_field, end_field


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
            "and optional in-place line flipping. Fully supports Arabic and international environments."
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
        if parameters[7].value:
            parameters[8].enabled = True
            parameters[9].enabled = True
            parameters[10].enabled = True
        else:
            parameters[8].enabled = False
            parameters[9].enabled = False
            parameters[10].enabled = False
            parameters[8].value = None
            parameters[9].value = False

        if parameters[9].value:
            parameters[12].enabled = True
        else:
            parameters[12].enabled = False
            parameters[12].value = False

    def updateMessages(self, parameters):
        """Modify messages created by internal validation."""
        if parameters[7].value and not parameters[8].value:
            parameters[8].setWarningMessage("Please select an Invert Elevation field from the node points layer to enable slope analysis.")
        if parameters[4].value and parameters[4].value <= 0:
            parameters[4].setErrorMessage("Arrow Base Width must be greater than zero.")
        if parameters[5].value and parameters[5].value <= 0:
            parameters[5].setErrorMessage("Arrow Height must be greater than zero.")
        if parameters[10].value and parameters[10].value <= 0:
            parameters[10].setErrorMessage("Search tolerance must be greater than zero.")

    def execute(self, parameters, messages):
        """Execute the tool with full Arabic path/data support and robust node alignment."""
        t_start = time.time()

        input_layer = to_unicode(parameters[0].valueAsText)
        output_workspace = to_unicode(parameters[1].valueAsText)
        output_layer_name = to_unicode(parameters[2].valueAsText)
        geom_type = to_unicode(parameters[3].valueAsText or "Polygon")
        triangle_base = float(parameters[4].value)
        triangle_height = float(parameters[5].value)
        transfer_attributes = bool(parameters[6].value)

        point_layer = to_unicode(parameters[7].valueAsText) if parameters[7].value else None
        invert_field = to_unicode(parameters[8].valueAsText) if parameters[8].value else None
        flip_reversed_pipes = bool(parameters[9].value) if parameters[9].value else False
        search_tolerance = float(parameters[10].value) if parameters[10].value else 1.5
        arrow_placement = to_unicode(parameters[11].valueAsText or "Midpoint (50%)")
        swap_invert_fields = bool(parameters[12].value) if parameters[12].value is not None else True

        # Validate workspaces
        if not arcpy.Exists(output_workspace):
            arcpy.AddError(to_unicode(u"Specified output workspace does not exist: {}".format(output_workspace)))
            return

        if not arcpy.Exists(input_layer):
            arcpy.AddError(to_unicode(u"Input pipe layer does not exist: {}".format(input_layer)))
            return

        output_layer = os.path.join(output_workspace, output_layer_name)

        if arcpy.Exists(output_layer):
            try:
                arcpy.Delete_management(output_layer)
                arcpy.AddMessage(to_unicode(u"Overwriting existing layer: {}".format(output_layer_name)))
            except Exception:
                pass

        # Extract spatial reference
        desc = arcpy.Describe(input_layer)
        spatial_ref = desc.spatialReference
        sr_name = spatial_ref.name if spatial_ref else "Unknown"
        arcpy.AddMessage(to_unicode(u"Spatial Reference: {}".format(sr_name)))

        # Parse placement ratio
        placement_ratio = 0.5
        if "25" in arrow_placement or "Quarter" in arrow_placement:
            placement_ratio = 0.25
        elif "75" in arrow_placement or "Three-Quarters" in arrow_placement:
            placement_ratio = 0.75

        # -------------------------------------------------------------------
        # Node Points Invert Indexing (Multi-Tier & Arabic Safe)
        # -------------------------------------------------------------------
        point_grid = {}
        search_tol = max(0.05, search_tolerance)
        soft_tol = search_tol * 1.5  # Soft snapping tolerance for slightly offset node points
        cell_size = max(soft_tol, 1.0)
        use_node_inverts = False
        node_point_count = 0

        if point_layer and invert_field and arcpy.Exists(point_layer):
            arcpy.AddMessage(to_unicode(u"Node Points Layer provided: {} (Field: '{}', Snapping Tolerance: {}m)".format(
                point_layer, invert_field, search_tol
            )))
            arcpy.AddMessage(to_unicode(u"Indexing node points and preparing slope percentage evaluation..."))
            inv_f_read = to_native_str(invert_field) if sys.version_info[0] < 3 else to_unicode(invert_field)
            sh_x = to_native_str("SHAPE@X") if sys.version_info[0] < 3 else "SHAPE@X"
            sh_y = to_native_str("SHAPE@Y") if sys.version_info[0] < 3 else "SHAPE@Y"
            try:
                with arcpy.da.SearchCursor(point_layer, [sh_x, sh_y, inv_f_read], spatial_reference=spatial_ref) as pt_cur:
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
                arcpy.AddMessage(to_unicode(u"Successfully indexed {} node points with valid invert elevations.".format(node_point_count)))
                use_node_inverts = True if node_point_count > 0 else False
            except Exception as e_pt:
                arcpy.AddWarning(to_unicode(u"Could not process node points layer: {}. Invert and slope calculation will be skipped.".format(to_unicode(e_pt))))
        else:
            arcpy.AddMessage(to_unicode(u"Optional node points layer not specified. Tool will generate flow arrows based on digitized line direction."))

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
        arcpy.AddMessage(to_unicode(u"Created output {} feature class: {}".format(fc_geom_type, output_layer_name)))

        # Add engineering tracking & QA/QC fields (Length 255 for bilingual messages)
        arcpy.AddField_management(output_layer, "ORIG_FID", "LONG", field_alias="Original Pipe FID / رقم الماسورة الأصلية")
        arcpy.AddField_management(output_layer, "QA_FLOW_STATUS", "TEXT", field_length=255, field_alias="Flow QA/QC Status / حالة السريان والتدقيق")
        arcpy.AddField_management(output_layer, "QA_SEVERITY", "TEXT", field_length=30, field_alias="QA Severity Code / كود الحالة")
        arcpy.AddField_management(output_layer, "START_INV", "DOUBLE", field_alias="Start Invert Elevation (m) / منسوب قاع البداية")
        arcpy.AddField_management(output_layer, "END_INV", "DOUBLE", field_alias="End Invert Elevation (m) / منسوب قاع النهاية")
        arcpy.AddField_management(output_layer, "INVERT_DROP", "DOUBLE", field_alias="Invert Drop / Head (m) / فرق المنسوب")
        arcpy.AddField_management(output_layer, "PIPE_LEN", "DOUBLE", field_alias="Pipe Length (m) / طول الماسورة")
        arcpy.AddField_management(output_layer, "SLOPE_PCT", "DOUBLE", field_alias="Hydraulic Slope (%) / نسبة الميل المئوية")
        arcpy.AddField_management(output_layer, "SLOPE_PER_MIL", "DOUBLE", field_alias="Hydraulic Slope (per mil) / الميل في الألف")
        arcpy.AddField_management(output_layer, "FLIPPED", "TEXT", field_length=10, field_alias="Flipped In-Place / تم عكس الخط")

        input_fields = [f.name for f in arcpy.ListFields(input_layer)]
        input_field_objs = {f.name: f for f in arcpy.ListFields(input_layer)}

        # Detect pipe invert fields (Arabic and English standards)
        st_inv_line_field, end_inv_line_field = find_pipe_invert_fields(input_fields)

        # Attributes transfer setup (Arabic field names validated)
        fields_to_copy = []
        managed_fields = {
            "ORIG_FID", "QA_FLOW_STATUS", "QA_SEVERITY",
            "START_INV", "END_INV", "INVERT_DROP", "PIPE_LEN",
            "SLOPE_PCT", "SLOPE_PER_MIL", "FLIPPED"
        }

        if transfer_attributes:
            for f in input_fields:
                f_obj = input_field_objs[f]
                f_name_u = to_unicode(f_obj.name)
                if f_obj.type in ("OID", "Geometry") or f_name_u.upper().startswith("SHAPE"):
                    continue
                if f_name_u.upper() in managed_fields:
                    continue
                try:
                    valid_name = arcpy.ValidateFieldName(f_obj.name, output_workspace)
                    arcpy.AddField_management(
                        output_layer, valid_name, f_obj.type,
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
            "SHAPE@", "ORIG_FID", "QA_FLOW_STATUS", "QA_SEVERITY",
            "START_INV", "END_INV", "INVERT_DROP", "PIPE_LEN",
            "SLOPE_PCT", "SLOPE_PER_MIL", "FLIPPED"
        ] + fields_to_copy

        # Identify index of pipe invert attributes for fallback
        st_field_idx = None
        end_field_idx = None
        if st_inv_line_field and st_inv_line_field in fields_to_copy:
            st_field_idx = 2 + fields_to_copy.index(st_inv_line_field)
        if end_inv_line_field and end_inv_line_field in fields_to_copy:
            end_field_idx = 2 + fields_to_copy.index(end_inv_line_field)

        # Statistics counters
        total_pipes = 0
        normal_count = 0
        reversed_count = 0
        flat_count = 0
        partial_count = 0
        start_missing_count = 0
        end_missing_count = 0
        unlinked_count = 0
        reversed_pipe_oids = []

        try:
            count_res = arcpy.GetCount_management(input_layer)
            total_features_est = int(count_res.getOutput(0))
            arcpy.SetProgressor("step", "Processing flow arrows...", 0, total_features_est, 1)
        except Exception:
            total_features_est = 0

        with arcpy.da.SearchCursor(input_layer, search_fields, spatial_reference=spatial_ref) as cursor:
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

                    # Extract line attribute inverts for fallback
                    pipe_st_val = None
                    pipe_end_val = None
                    if st_field_idx is not None:
                        try:
                            v = row[st_field_idx]
                            if v is not None:
                                pipe_st_val = float(v)
                        except (ValueError, TypeError):
                            pass
                    if end_field_idx is not None:
                        try:
                            v = row[end_field_idx]
                            if v is not None:
                                pipe_end_val = float(v)
                        except (ValueError, TypeError):
                            pass

                    # -------------------------------------------------------
                    # Invert Evaluation & Hydraulic Slope Calculation:
                    # Multi-tier snapping: Exact tolerance -> Soft tolerance -> Pipe attributes
                    # -------------------------------------------------------
                    st_inv = None
                    end_inv = None
                    inv_drop = None
                    slope_pct = None
                    slope_per_mil = None
                    is_reversed = False
                    qa_severity = "DIGITIZED_ONLY"
                    qa_status = u"Normal Flow (Digitized Direction) / سريان طبيعي وفق اتجاه الرسم"

                    if use_node_inverts:
                        # Resolve Start Invert
                        st_inv = get_nearest_invert(start_point.X, start_point.Y, max_dist=search_tol)
                        if st_inv is None:
                            st_inv = get_nearest_invert(start_point.X, start_point.Y, max_dist=soft_tol)
                        if st_inv is None and pipe_st_val is not None:
                            st_inv = pipe_st_val

                        # Resolve End Invert
                        end_inv = get_nearest_invert(end_point.X, end_point.Y, max_dist=search_tol)
                        if end_inv is None:
                            end_inv = get_nearest_invert(end_point.X, end_point.Y, max_dist=soft_tol)
                        if end_inv is None and pipe_end_val is not None:
                            end_inv = pipe_end_val

                        # Case A: Both node inverts determined
                        if st_inv is not None and end_inv is not None:
                            st_inv = round(st_inv, 4)
                            end_inv = round(end_inv, 4)
                            inv_drop = round(st_inv - end_inv, 4)

                            if pipe_len > 0:
                                slope_pct = round((inv_drop / pipe_len) * 100.0, 4)
                                slope_per_mil = round((inv_drop / pipe_len) * 1000.0, 3)

                            if st_inv > end_inv:
                                qa_severity = "NORMAL_DOWNHILL"
                                qa_status = u"Normal Downhill Flow (Drop={:+.3f}m, Slope={:.2f}%)".format(inv_drop, slope_pct or 0.0)
                                normal_count += 1
                            elif st_inv < end_inv:
                                is_reversed = True
                                qa_severity = "ADVERSE_SLOPE"
                                qa_status = u"REVERSED - Flow Corrected Downhill (Adverse Drop={:+.3f}m, Slope={:.2f}%)".format(inv_drop, slope_pct or 0.0)
                                reversed_count += 1
                                reversed_pipe_oids.append(orig_fid)
                            else:
                                qa_severity = "ZERO_SLOPE"
                                qa_status = u"Flat Pipe (Zero Invert Drop / Slope=0.00%)"
                                flat_count += 1

                        # Case B: Pipe did NOT start with a node point (Start Missing, End Found)
                        elif st_inv is None and end_inv is not None:
                            end_inv = round(end_inv, 4)
                            qa_severity = "PARTIAL_START_MISSING"
                            qa_status = u"Partial Invert: Start Node Missing / End Node Found ({:.3f}m) - Arrow Follows Digitized".format(end_inv)
                            partial_count += 1
                            start_missing_count += 1

                        # Case C: Pipe did NOT end with a node point (Start Found, End Missing)
                        elif st_inv is not None and end_inv is None:
                            st_inv = round(st_inv, 4)
                            qa_severity = "PARTIAL_END_MISSING"
                            qa_status = u"Partial Invert: Start Node Found ({:.3f}m) / End Node Missing - Arrow Follows Digitized".format(st_inv)
                            partial_count += 1
                            end_missing_count += 1

                        # Case D: Unlinked pipe (Neither start nor end node found within tolerance)
                        else:
                            qa_severity = "UNLINKED_NODES"
                            qa_status = u"Unlinked Pipe: Neither Start nor End Node Found - Arrow Follows Digitized"
                            unlinked_count += 1
                    else:
                        normal_count += 1

                    # Set arrow angle: If reversed via node inverts, flip 180 degrees to point downhill
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
                        arrow_geom, orig_fid, qa_status, qa_severity,
                        st_inv, end_inv, inv_drop, pipe_len,
                        slope_pct, slope_per_mil, flipped_flag
                    ] + attr_values
                    insert_cursor.insertRow(insert_row)

        try:
            arcpy.ResetProgressor()
        except Exception:
            pass

        # In-Place Pipe Line Geometry Flipping (Only when node inverts reversed)
        flipped_count = 0
        if flip_reversed_pipes and reversed_pipe_oids:
            reversed_oids_set = set(reversed_pipe_oids)
            arcpy.AddMessage(to_unicode(u"Auto-flipping {} reversed pipe line(s) in-place to follow gravity flow...".format(len(reversed_oids_set))))

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

                                # Swap start and end invert attributes on the pipe feature if available
                                if s_up_idx is not None and e_up_idx is not None:
                                    old_st = up_row[s_up_idx]
                                    old_end = up_row[e_up_idx]
                                    up_row[s_up_idx] = old_end
                                    up_row[e_up_idx] = old_st

                                up_cursor.updateRow(up_row)
                                flipped_count += 1
                arcpy.AddMessage(to_unicode(u"Successfully flipped {} pipe line(s) in the input layer.".format(flipped_count)))
            except Exception as ex_flip:
                arcpy.AddWarning(to_unicode(u"Could not flip pipe lines in-place (layer may be locked or read-only): {}".format(to_unicode(ex_flip))))

        # Execution Summary Output (Bilingual Arabic & English)
        elapsed = round(time.time() - t_start, 2)

        if use_node_inverts:
            pct_norm = (normal_count / total_pipes * 100.0) if total_pipes else 0.0
            pct_rev = (reversed_count / total_pipes * 100.0) if total_pipes else 0.0
            pct_flat = (flat_count / total_pipes * 100.0) if total_pipes else 0.0
            pct_part = (partial_count / total_pipes * 100.0) if total_pipes else 0.0
            pct_unlink = (unlinked_count / total_pipes * 100.0) if total_pipes else 0.0

            summary_banner = u"""
======================================================================
  🌊 CREATE FLOW ARROW & QA/QC AUDIT ENGINE - SUMMARY
  تقرير تدقيق ومراجعة اتجاهات السريان والميول الهيدروليكية
======================================================================
  Mode / نمط التشغيل:            Smart Node Invert Alignment & Slope QA/QC
  Node Points Layer / طبقة النقاط: {} (Field: '{}')
  Total Pipes Analyzed / إجمالي المواسير: {}
  - Normal Downhill Flow / سريان طبيعي مع الانحدار:  {} ({:.1f}%)
  - Adverse Slope (Reversed) / ميول عكسية:           {} ({:.1f}%)
  - Flat Pipes (Zero Drop) / خطوط مستوية:            {} ({:.1f}%)
  - Partial Inverts / مناسيب جزئية (نقطة واحدة):      {} ({:.1f}%)
    * Start Node Missing / لم تبدأ بنقطة منهل:       {}
    * End Node Missing / لم تنتهِ بنقطة منهل:        {}
  - Unlinked Pipes / مواسير غير مرتبطة بنقاط:        {} ({:.1f}%)
  ------------------------------------------------------------------
  Hydraulic Slopes / حساب الميول الهيدروليكية:       YES (SLOPE_PCT & SLOPE_PER_MIL)
  In-Place Auto-Flip / تصحيح رسم الخطوط المعكوسة:    {} pipe(s) corrected
  Output Feature Class / الطبقة الناتجة:             {}
  Elapsed Execution Time / زمن التنفيذ:              {} seconds
======================================================================
""".format(
                point_layer, invert_field,
                total_pipes,
                normal_count, pct_norm,
                reversed_count, pct_rev,
                flat_count, pct_flat,
                partial_count, pct_part,
                start_missing_count,
                end_missing_count,
                unlinked_count, pct_unlink,
                flipped_count,
                output_layer,
                elapsed
            )
        else:
            summary_banner = u"""
======================================================================
  🌊 CREATE FLOW ARROW - SUMMARY
  تقرير إنشاء أسهم اتجاه السريان
======================================================================
  Mode / نمط التشغيل:            Standard Flow Arrows (Digitized Direction)
  Node Points Layer / طبقة النقاط: Not Specified (Slope & Invert Analysis Skipped)
  Total Pipes Processed / إجمالي المواسير: {}
  Flow Arrows Generated / الأسهم المنشأة:  {} ({})
  Output Feature Class / الطبقة الناتجة:   {}
  Elapsed Execution Time / زمن التنفيذ:    {} seconds
======================================================================
""".format(
                total_pipes,
                total_pipes, fc_geom_type,
                output_layer,
                elapsed
            )

        arcpy.AddMessage(summary_banner)

        if start_missing_count > 0:
            arcpy.AddMessage(to_unicode(u"ℹ️ ملاحظة هندسية: تم العثور على {} ماسورة لم تبدأ بنقطة منهل، وتم توليد أسهم السريان لها بنجاح وفقاً لاتجاه الرسم الرقمي.".format(start_missing_count)))
            arcpy.AddMessage(to_unicode(u"Note: Found {} pipe(s) with missing start node; flow arrows generated successfully following digitized direction.".format(start_missing_count)))

        if reversed_count > 0 and not flip_reversed_pipes:
            arcpy.AddWarning(to_unicode(
                u"⚠️ تنبيه QA/QC: تم رصد {} ماسورة ذات ميول عكسية. وجّهت الأسهم مع الجاذبية (downhill). لتصحيح اتجاه رسم الخطوط في الطبقة الأصلية، فعّل خيار 'Auto-Flip'.".format(reversed_count)
            ))
            arcpy.AddWarning(to_unicode(
                u"QA/QC Alert: Identified {} pipe(s) with adverse/reversed slope. Arrows oriented downhill. Enable 'Auto-Flip' to correct in-place.".format(reversed_count)
            ))

        # Pass output to derived parameter
        parameters[13].value = output_layer

        # Auto-add to active map session
        self._add_to_active_map(output_layer)

    def _add_to_active_map(self, layer_path):
        """Add output layer to the active map session (ArcGIS Pro or ArcMap)."""
        layer_path_u = to_unicode(layer_path)
        if hasattr(arcpy, "mp"):
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                active_map = aprx.activeMap or (aprx.listMaps()[0] if aprx.listMaps() else None)
                if active_map:
                    active_map.addDataFromPath(layer_path_u)
                    arcpy.AddMessage(to_unicode(u"(ArcGIS Pro): Layer added to active map successfully."))
                    return True
            except Exception:
                return False

        elif hasattr(arcpy, "mapping"):
            try:
                mxd = arcpy.mapping.MapDocument("CURRENT")
                df = arcpy.mapping.ListDataFrames(mxd)[0]
                new_layer = arcpy.mapping.Layer(layer_path_u)
                arcpy.mapping.AddLayer(df, new_layer)
                arcpy.RefreshTOC()
                arcpy.RefreshActiveView()
                arcpy.AddMessage(to_unicode(u"(ArcMap): Layer added to active data frame successfully."))
                return True
            except Exception:
                return False

        return False
