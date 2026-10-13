# -*- coding: utf-8 -*-
"""
CreateFlowArrow.py
------------------
Unified geoprocessing script for generating flow direction arrows on gravity infrastructure networks.
Fully compatible with ArcGIS Pro (Python 3.x) and ArcMap 10.1+ (Python 2.7).

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
                       transfer_attributes=True):
    """
    Main routine to generate flow direction arrow geometries (Polygon or Polyline).
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

    fc_geom_type = "POLYGON" if geometry_type.lower() == "polygon" else "POLYLINE"

    arcpy.CreateFeatureclass_management(
        out_path=output_workspace,
        out_name=output_layer_name,
        geometry_type=fc_geom_type,
        spatial_reference=spatial_ref
    )
    log_msg("Created output {} feature class: {}".format(fc_geom_type, output_layer_name))

    arcpy.AddField_management(output_layer, "ORIG_FID", "LONG", field_alias="Original Pipe FID")
    arcpy.AddField_management(output_layer, "QA_FLOW_STATUS", "TEXT", field_length=30,
                             field_alias="Flow QA/QC Status")

    input_fields = [f.name for f in arcpy.ListFields(input_layer)]
    input_field_objs = {f.name: f for f in arcpy.ListFields(input_layer)}

    st_inv_field = None
    end_inv_field = None
    for f in input_fields:
        f_upper = f.upper()
        if f_upper in ("ST_INV_M", "START_INV", "US_INVERT", "UPSTREAM_IL", "INV_IN"):
            st_inv_field = f
        elif f_upper in ("END_INV_M", "END_INV", "DS_INVERT", "DOWNSTREAM_IL", "INV_OUT"):
            end_inv_field = f

    fields_to_copy = []
    if transfer_attributes:
        for f in input_fields:
            f_obj = input_field_objs[f]
            if f_obj.type in ("OID", "Geometry") or f.upper().startswith("SHAPE"):
                continue
            if f.upper() in ("ORIG_FID", "QA_FLOW_STATUS"):
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
    insert_fields = ["SHAPE@", "ORIG_FID", "QA_FLOW_STATUS"] + fields_to_copy

    feature_count = 0
    reversed_count = 0

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

                angle = math.atan2(dy, dx)

                # Arrow geometry vertices
                base_left = arcpy.Point(
                    mid_point.X - (triangle_base / 2.0) * math.sin(angle),
                    mid_point.Y + (triangle_base / 2.0) * math.cos(angle)
                )
                base_right = arcpy.Point(
                    mid_point.X + (triangle_base / 2.0) * math.sin(angle),
                    mid_point.Y - (triangle_base / 2.0) * math.cos(angle)
                )
                tip = arcpy.Point(
                    mid_point.X + triangle_height * math.cos(angle),
                    mid_point.Y + triangle_height * math.sin(angle)
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

                qa_status = "Normal Flow"
                if st_inv_field and end_inv_field:
                    try:
                        st_idx = fields_to_copy.index(st_inv_field)
                        end_idx = fields_to_copy.index(end_inv_field)
                        st_val = attr_values[st_idx]
                        end_val = attr_values[end_idx]
                        if st_val is not None and end_val is not None:
                            if float(st_val) < float(end_val):
                                qa_status = "REVERSED (Adverse Slope)"
                                reversed_count += 1
                    except Exception:
                        pass

                insert_row = [arrow_geom, orig_fid, qa_status] + attr_values
                insert_cursor.insertRow(insert_row)
                feature_count += 1

    log_msg("Successfully generated {} flow direction arrows ({}).".format(feature_count, fc_geom_type))
    if reversed_count > 0:
        log_warn("QA/QC Alert: Detected {} pipe(s) with reversed flow direction against gravity!".format(reversed_count))

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

        create_flow_arrows(
            input_layer=input_layer,
            output_workspace=output_workspace,
            output_layer_name=output_layer_name,
            geometry_type=geom_type,
            triangle_base=triangle_base,
            triangle_height=triangle_height,
            transfer_attributes=transfer_attrs
        )

    except arcpy.ExecuteError:
        log_err(arcpy.GetMessages(2))
    except Exception as e:
        log_err(str(e))

if __name__ == '__main__':
    main()
