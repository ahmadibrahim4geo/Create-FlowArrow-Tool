# -*- coding: utf-8 -*-
"""
CreateFlowArrow.py
------------------
Unified geoprocessing script for generating flow direction arrows on gravity infrastructure networks.
Fully compatible with ArcGIS Pro (Python 3.x) and ArcMap 10.1+ (Python 2.7).

Features:
- Dual-platform execution (ArcMap & Pro).
- Tangent-aligned flow direction arrows (Polygon or Polyline).
- Centroid midpoint alignment.
- Optional Node/Manhole Points Layer with Invert Elevation comparison (Z_higher -> Z_lower).
- Downhill arrow orientation based on actual invert elevations.
- Auto-Flip reversed pipe lines in-place to correct digitized direction.

Author: Ahmad Ibrahim
Email: ahmadibrahim.geo@gmail.com
Repository: https://github.com/ahmadibrahim4geo/Create-FlowArrow-Tool.git
License: MIT
"""

from __future__ import print_function, division, absolute_import
import sys
import math
import os
import arcpy

# ---------------------------------------------------------------------------
# Logging & Active Map Utilities
# ---------------------------------------------------------------------------

def log_msg(msg):
    arcpy.AddMessage(msg)
    try:
        print(msg)
    except Exception:
        pass

def log_warn(msg):
    arcpy.AddWarning(msg)
    try:
        print("[WARNING] " + msg)
    except Exception:
        pass

def log_err(msg):
    arcpy.AddError(msg)
    try:
        print("[ERROR] " + msg)
    except Exception:
        pass

def add_to_active_map(layer_path):
    """Add output layer to the active map session (ArcGIS Pro or ArcMap)."""
    if hasattr(arcpy, "mp"):
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = aprx.activeMap or (aprx.listMaps()[0] if aprx.listMaps() else None)
            if active_map:
                active_map.addDataFromPath(layer_path)
                log_msg("(ArcGIS Pro): Layer added to active map successfully.")
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
            log_msg("(ArcMap): Layer added to active data frame successfully.")
            return True
        except Exception:
            return False

    return False

# ---------------------------------------------------------------------------
# Core Flow Arrow Generation Routine
# ---------------------------------------------------------------------------

def create_flow_arrows(input_layer, output_workspace, output_layer_name,
                       geometry_type="Polygon",
                       triangle_base=2.0, triangle_height=5.0,
                       transfer_attributes=True,
                       point_layer=None, invert_field=None,
                       flip_reversed_pipes=False):
    """
    Main routine to generate flow direction arrow geometries (Polygon or Polyline).
    Supports optional node points layer with invert elevation comparison and auto-flipping.
    """
    if not arcpy.Exists(output_workspace):
        log_err("Specified output workspace does not exist: {}".format(output_workspace))
        return None

    if not arcpy.Exists(input_layer):
        log_err("Input pipe lines layer does not exist: {}".format(input_layer))
        return None

    output_layer = os.path.join(output_workspace, output_layer_name)

    if arcpy.Exists(output_layer):
        try:
            arcpy.Delete_management(output_layer)
            log_msg("Overwriting existing layer: {}".format(output_layer_name))
        except Exception:
            pass

    desc = arcpy.Describe(input_layer)
    spatial_ref = desc.spatialReference
    sr_name = spatial_ref.name if spatial_ref else "Unknown"
    log_msg("Spatial Reference: {}".format(sr_name))

    # Build spatial index for Node Points if provided
    point_grid = {}
    cell_size = 2.0  # meter grid cell
    use_node_inverts = False

    if point_layer and invert_field and arcpy.Exists(point_layer):
        log_msg("Loading node points and building spatial index from: {}...".format(point_layer))
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
            log_msg("Successfully indexed {} node points with valid invert elevations.".format(point_count))
            use_node_inverts = True if point_count > 0 else False
        except Exception as e_pt:
            log_warn("Could not process node points layer: {}. Falling back to line attributes.".format(e_pt))

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

    fc_geom_type = "POLYGON" if geometry_type.lower() == "polygon" else "POLYLINE"

    arcpy.CreateFeatureclass_management(
        out_path=output_workspace,
        out_name=output_layer_name,
        geometry_type=fc_geom_type,
        spatial_reference=spatial_ref
    )
    log_msg("Created output {} feature class: {}".format(fc_geom_type, output_layer_name))

    arcpy.AddField_management(output_layer, "ORIG_FID", "LONG", field_alias="Original Pipe FID")
    arcpy.AddField_management(output_layer, "QA_FLOW_STATUS", "TEXT", field_length=50,
                             field_alias="Flow QA/QC Status")
    arcpy.AddField_management(output_layer, "START_INV", "DOUBLE", field_alias="Start Invert Elevation (m)")
    arcpy.AddField_management(output_layer, "END_INV", "DOUBLE", field_alias="End Invert Elevation (m)")
    arcpy.AddField_management(output_layer, "INVERT_DROP", "DOUBLE", field_alias="Invert Drop / Head (m)")

    input_fields = [f.name for f in arcpy.ListFields(input_layer)]
    input_field_objs = {f.name: f for f in arcpy.ListFields(input_layer)}

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

                # Calculate local tangent at midpoint
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

                # Orient arrow downhill
                if is_reversed:
                    arrow_angle = digitized_angle + math.pi
                    if arrow_angle > math.pi:
                        arrow_angle -= 2.0 * math.pi
                else:
                    arrow_angle = digitized_angle

                # Arrow geometry vertices
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

                # Centroid offset to pipe midpoint
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

    log_msg("Successfully generated {} flow direction arrows ({}).".format(feature_count, fc_geom_type))
    if reversed_count > 0:
        log_warn("QA/QC Alert: Identified {} pipe(s) with adverse/reversed slope. Arrows have been oriented downhill.".format(reversed_count))

    # Auto-Flip reversed pipes in-place
    if flip_reversed_pipes and reversed_pipe_oids:
        log_msg("Auto-flipping {} reversed pipe line(s) in-place to follow gravity flow...".format(len(reversed_pipe_oids)))
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
            log_msg("Successfully flipped {} pipe line(s) in the input layer.".format(flipped_count))
        except Exception as ex_flip:
            log_warn("Could not flip pipe lines in-place (layer may be locked or read-only): {}".format(ex_flip))

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
            flip_reversed_pipes=flip_reversed
        )

    except arcpy.ExecuteError:
        log_err(arcpy.GetMessages(2))
    except Exception as e:
        log_err(str(e))

if __name__ == '__main__':
    main()
