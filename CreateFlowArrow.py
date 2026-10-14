# -*- coding: utf-8 -*-
"""
CreateFlowArrow.py
------------------
High-Performance Geoprocessing Engine for Generating Flow Direction Arrows
and QA/QC Slope Auditing on Gravity Infrastructure Networks.

Fully compatible with:
- ArcGIS Pro 2.x & 3.x (Python 3.x)
- ArcMap 10.1+ (Python 2.7)
- Arabic and International Paths, Geodatabases, Layer Names, and Field Data

Key Capabilities:
1. Dual-Platform Execution: Automatic environment detection (mp vs mapping).
2. Full Arabic Language Support:
   - Robust Unicode encoding/decoding across Windows file paths, Arabic folder names,
     Arabic Geodatabases (.gdb), Arabic layer names, and Arabic attribute fields/aliases.
   - Safe logging that prevents console codepage crashes in English and Arabic locales.
3. Smart Node Invert & Hydraulic Slope Engine:
   - Evaluated strictly when the user provides the Optional Node Points Layer and Invert Elevation Field.
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
5. Centroid Midpoint Alignment: Analytical offset so arrow center-of-gravity coincides with line placement.
6. Instantaneous Curve Tangents: Evaluates derivative along line trajectory.
7. In-Place Pipe Flipping: Reverses polyline geometry (including multi-part) for reversed slope pipes.
8. Performance & Scaling: O(1) spatial grid, SetProgressor visual progress bar, O(1) set lookups.

Author: Ahmad Ibrahim
Email: ahmadibrahim.geo@gmail.com
Repository: https://github.com/ahmadibrahim4geo/Create-FlowArrow-Tool.git
License: MIT
"""

from __future__ import print_function, division, absolute_import
import sys
import math
import os
import time
import arcpy

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
# Logging & Active Map Utilities
# ---------------------------------------------------------------------------

def log_msg(msg):
    u_msg = to_unicode(msg)
    try:
        arcpy.AddMessage(u_msg)
    except Exception:
        try:
            arcpy.AddMessage(to_native_str(u_msg))
        except Exception:
            pass
    try:
        if sys.version_info[0] < 3:
            print(u_msg.encode(sys.stdout.encoding or "utf-8", "replace"))
        else:
            print(u_msg)
    except Exception:
        pass

def log_warn(msg):
    u_msg = to_unicode(msg)
    try:
        arcpy.AddWarning(u_msg)
    except Exception:
        try:
            arcpy.AddWarning(to_native_str(u_msg))
        except Exception:
            pass
    try:
        if sys.version_info[0] < 3:
            print((u"[WARNING] " + u_msg).encode(sys.stdout.encoding or "utf-8", "replace"))
        else:
            print(u"[WARNING] " + u_msg)
    except Exception:
        pass

def log_err(msg):
    u_msg = to_unicode(msg)
    try:
        arcpy.AddError(u_msg)
    except Exception:
        try:
            arcpy.AddError(to_native_str(u_msg))
        except Exception:
            pass
    try:
        if sys.version_info[0] < 3:
            print((u"[ERROR] " + u_msg).encode(sys.stdout.encoding or "utf-8", "replace"))
        else:
            print(u"[ERROR] " + u_msg)
    except Exception:
        pass

def add_to_active_map(layer_path):
    """Add output layer to the active map session (ArcGIS Pro or ArcMap)."""
    if hasattr(arcpy, "mp"):
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = aprx.activeMap or (aprx.listMaps()[0] if aprx.listMaps() else None)
            if active_map:
                active_map.addDataFromPath(to_unicode(layer_path))
                log_msg(u"(ArcGIS Pro): Layer added to active map successfully.")
                return True
        except Exception:
            return False

    elif hasattr(arcpy, "mapping"):
        try:
            mxd = arcpy.mapping.MapDocument("CURRENT")
            df = arcpy.mapping.ListDataFrames(mxd)[0]
            new_layer = arcpy.mapping.Layer(to_unicode(layer_path))
            arcpy.mapping.AddLayer(df, new_layer)
            arcpy.RefreshTOC()
            arcpy.RefreshActiveView()
            log_msg(u"(ArcMap): Layer added to active data frame successfully.")
            return True
        except Exception:
            return False

    return False

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

# ---------------------------------------------------------------------------
# Core Flow Arrow Generation Routine
# ---------------------------------------------------------------------------

def create_flow_arrows(input_layer, output_workspace, output_layer_name,
                       geometry_type="Polygon",
                       triangle_base=2.0, triangle_height=5.0,
                       transfer_attributes=True,
                       point_layer=None, invert_field=None,
                       flip_reversed_pipes=False,
                       search_tolerance=1.5,
                       arrow_placement="Midpoint (50%)",
                       swap_invert_fields=True):
    """
    Main routine to generate flow direction arrow geometries (Polygon or Polyline).
    Slope percentage and invert elevation evaluations are strictly performed
    when the optional node points layer and invert elevation field are provided.
    Fully supports Arabic paths, workspaces, layer names, and attributes.
    """
    t_start = time.time()

    input_layer = to_unicode(input_layer)
    output_workspace = to_unicode(output_workspace)
    output_layer_name = to_unicode(output_layer_name)
    point_layer = to_unicode(point_layer) if point_layer else None
    invert_field = to_unicode(invert_field) if invert_field else None
    arrow_placement = to_unicode(arrow_placement) if arrow_placement else u"Midpoint (50%)"
    geometry_type = to_unicode(geometry_type) if geometry_type else u"Polygon"

    if not arcpy.Exists(output_workspace):
        log_err(u"Specified output workspace does not exist: {}".format(output_workspace))
        return None

    if not arcpy.Exists(input_layer):
        log_err(u"Input pipe lines layer does not exist: {}".format(input_layer))
        return None

    output_layer = os.path.join(output_workspace, output_layer_name)

    if arcpy.Exists(output_layer):
        try:
            arcpy.Delete_management(output_layer)
            log_msg(u"Overwriting existing layer: {}".format(output_layer_name))
        except Exception:
            pass

    desc = arcpy.Describe(input_layer)
    spatial_ref = desc.spatialReference
    sr_name = spatial_ref.name if spatial_ref else "Unknown"
    log_msg(u"Spatial Reference: {}".format(sr_name))

    # Parse arrow placement ratio
    placement_ratio = 0.5
    if "25" in arrow_placement or "Quarter" in arrow_placement:
        placement_ratio = 0.25
    elif "75" in arrow_placement or "Three-Quarters" in arrow_placement:
        placement_ratio = 0.75

    # -----------------------------------------------------------------------
    # Node Points Layer Invert Indexing (Multi-Tier & Arabic Safe)
    # -----------------------------------------------------------------------
    point_grid = {}
    search_tol = max(0.05, float(search_tolerance)) if search_tolerance else 1.5
    soft_tol = search_tol * 1.5  # Soft snapping tolerance for slightly offset node points
    cell_size = max(soft_tol, 1.0)
    use_node_inverts = False
    node_point_count = 0

    if point_layer and invert_field and arcpy.Exists(point_layer):
        log_msg(u"Node Points Layer provided: {} (Field: '{}', Snapping Tolerance: {}m)".format(
            point_layer, invert_field, search_tol
        ))
        log_msg(u"Indexing node points and preparing slope percentage evaluation...")
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
            log_msg(u"Successfully indexed {} node points with valid invert elevations.".format(node_point_count))
            use_node_inverts = True if node_point_count > 0 else False
        except Exception as e_pt:
            log_warn(u"Could not process node points layer: {}. Invert and slope calculation will be skipped.".format(to_unicode(e_pt)))
    else:
        log_msg(u"Optional node points layer not specified. Tool will generate flow arrows based on digitized line direction.")

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

    fc_geom_type = "POLYGON" if str(geometry_type).lower() == "polygon" else "POLYLINE"

    arcpy.CreateFeatureclass_management(
        out_path=output_workspace,
        out_name=output_layer_name,
        geometry_type=fc_geom_type,
        spatial_reference=spatial_ref
    )
    log_msg(u"Created output {} feature class: {}".format(fc_geom_type, output_layer_name))

    # Add core tracking & QA/QC engineering fields (Length 255 for bilingual messages)
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

    # Manage attribute transfer (Arabic field names validated for shapefile/geodatabase)
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

    # Initialize progressor if supported
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

                # Instantaneous tangent at designated placement along line
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

                # -----------------------------------------------------------
                # Invert Evaluation & Hydraulic Slope Calculation:
                # Multi-tier snapping: Exact tolerance -> Soft tolerance -> Pipe attributes
                # -----------------------------------------------------------
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

                # Orient arrow: if adverse slope detected via node inverts, orient downhill
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

                # Centroid offset to pipe anchor point
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

    # -----------------------------------------------------------------------
    # In-Place Pipe Line Geometry Flipping (Only when node inverts reversed)
    # -----------------------------------------------------------------------
    flipped_count = 0
    if flip_reversed_pipes and reversed_pipe_oids:
        reversed_oids_set = set(reversed_pipe_oids)
        log_msg(u"Auto-flipping {} reversed pipe line(s) in-place to follow gravity flow...".format(len(reversed_oids_set)))

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
            log_msg(u"Successfully flipped {} pipe line(s) in the input layer.".format(flipped_count))
        except Exception as ex_flip:
            log_warn(u"Could not flip pipe lines in-place (layer may be locked or read-only): {}".format(to_unicode(ex_flip)))

    # -----------------------------------------------------------------------
    # Execution Summary Output (Bilingual Arabic & English)
    # -----------------------------------------------------------------------
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

    log_msg(summary_banner)

    if start_missing_count > 0:
        log_msg(u"ℹ️ ملاحظة هندسية: تم العثور على {} ماسورة لم تبدأ بنقطة منهل، وتم توليد أسهم السريان لها بنجاح وفقاً لاتجاه الرسم الرقمي.".format(start_missing_count))
        log_msg(u"Note: Found {} pipe(s) with missing start node; flow arrows generated successfully following digitized direction.".format(start_missing_count))

    if reversed_count > 0 and not flip_reversed_pipes:
        log_warn(u"⚠️ تنبيه QA/QC: تم رصد {} ماسورة ذات ميول عكسية. وجّهت الأسهم مع الجاذبية (downhill). لتصحيح اتجاه رسم الخطوط في الطبقة الأصلية، فعّل خيار 'Auto-Flip'.".format(reversed_count))
        log_warn(u"QA/QC Alert: Identified {} pipe(s) with adverse/reversed slope. Arrows oriented downhill. Enable 'Auto-Flip' to correct in-place.".format(reversed_count))

    add_to_active_map(output_layer)
    return output_layer

# ---------------------------------------------------------------------------
# Script Tool Entry Point
# ---------------------------------------------------------------------------

def main():
    try:
        input_layer = arcpy.GetParameterAsText(0)
        output_workspace = arcpy.GetParameterAsText(1)
        output_layer_name = arcpy.GetParameterAsText(2)
        geom_type = arcpy.GetParameterAsText(3) or "Polygon"
        triangle_base = float(arcpy.GetParameterAsText(4))
        triangle_height = float(arcpy.GetParameterAsText(5))

        transfer_attrs = True
        if arcpy.GetArgumentCount() > 6:
            val = arcpy.GetParameterAsText(6)
            if val and val.lower() in ("false", "0", "no"):
                transfer_attrs = False

        point_layer = arcpy.GetParameterAsText(7) if arcpy.GetArgumentCount() > 7 else None
        if point_layer == "":
            point_layer = None

        invert_field = arcpy.GetParameterAsText(8) if arcpy.GetArgumentCount() > 8 else None
        if invert_field == "":
            invert_field = None

        flip_reversed = False
        if arcpy.GetArgumentCount() > 9:
            val_flip = arcpy.GetParameterAsText(9)
            if val_flip and val_flip.lower() in ("true", "1", "yes"):
                flip_reversed = True

        search_tolerance = 1.5
        if arcpy.GetArgumentCount() > 10:
            val_tol = arcpy.GetParameterAsText(10)
            if val_tol:
                try:
                    search_tolerance = float(val_tol)
                except ValueError:
                    pass

        arrow_placement = "Midpoint (50%)"
        if arcpy.GetArgumentCount() > 11:
            val_place = arcpy.GetParameterAsText(11)
            if val_place:
                arrow_placement = val_place

        swap_inverts = True
        if arcpy.GetArgumentCount() > 12:
            val_swap = arcpy.GetParameterAsText(12)
            if val_swap and val_swap.lower() in ("false", "0", "no"):
                swap_inverts = False

        create_flow_arrows(
            input_layer=input_layer,
            output_workspace=output_workspace,
            output_layer_name=output_layer_name,
            geometry_type=geom_type,
            triangle_base=triangle_base,
            triangle_height=triangle_height,
            transfer_attributes=transfer_attrs,
            point_layer=point_layer,
            invert_field=invert_field,
            flip_reversed_pipes=flip_reversed,
            search_tolerance=search_tolerance,
            arrow_placement=arrow_placement,
            swap_invert_fields=swap_inverts
        )

    except arcpy.ExecuteError:
        log_err(arcpy.GetMessages(2))
    except Exception as e:
        log_err(to_unicode(e))

if __name__ == '__main__':
    main()
