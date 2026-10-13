# -*- coding: utf-8 -*-
"""
CreateFlowArrow.pyt
-------------------
Unified ArcGIS Python Toolbox for generating flow direction arrows on gravity infrastructure networks.
Fully compatible with ArcGIS Pro (Python 3.x) and ArcMap 10.1+ (Python 2.7).

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
            "pipe digitization direction (Start Node to End Node) for gravity networks "
            "(stormwater, sewer, groundwater lowering), with automated elevation QA/QC auditing."
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

        # 6. Transfer Attributes
        param6 = arcpy.Parameter(
            displayName="Transfer Pipe Attributes",
            name="transfer_attributes",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        param6.value = True

        # 7. Derived Output (For auto-adding to active map)
        param7 = arcpy.Parameter(
            displayName="Output Flow Arrows Layer",
            name="output_feature_class",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output"
        )
        param7.parameterDependencies = [param1.name]

        return [param0, param1, param2, param3, param4, param5, param6, param7]

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation."""
        return

    def updateMessages(self, parameters):
        """Modify messages created by internal validation."""
        return

    def execute(self, parameters, messages):
        """Execute the tool."""
        input_layer = parameters[0].valueAsText
        output_workspace = parameters[1].valueAsText
        output_layer_name = parameters[2].valueAsText
        geom_type = parameters[3].valueAsText  # "Polygon" or "Polyline"
        triangle_base = float(parameters[4].value)
        triangle_height = float(parameters[5].value)
        transfer_attributes = bool(parameters[6].value)

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
        arcpy.AddField_management(output_layer, "QA_FLOW_STATUS", "TEXT", field_length=30,
                                 field_alias="Flow QA/QC Status")

        # Inspect fields for attribute transfer
        input_fields = [f.name for f in arcpy.ListFields(input_layer)]
        input_field_objs = {f.name: f for f in arcpy.ListFields(input_layer)}

        # Detect invert elevation fields for automated QA/QC check
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

                    # Calculate local tangent angle at pipe midpoint
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

                    # Compute arrow head vertices
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

                    # Calculate triangle centroid and adjust offset to pipe midpoint
                    mid_tri_x = (base_left.X + base_right.X + tip.X) / 3.0
                    mid_tri_y = (base_left.Y + base_right.Y + tip.Y) / 3.0

                    off_x = mid_point.X - mid_tri_x
                    off_y = mid_point.Y - mid_tri_y

                    base_left_adj = arcpy.Point(base_left.X + off_x, base_left.Y + off_y)
                    base_right_adj = arcpy.Point(base_right.X + off_x, base_right.Y + off_y)
                    tip_adj = arcpy.Point(tip.X + off_x, tip.Y + off_y)

                    # Construct requested geometry type
                    if fc_geom_type == "POLYGON":
                        # Closed triangular polygon arrow
                        arrow_geom = arcpy.Polygon(
                            arcpy.Array([base_left_adj, base_right_adj, tip_adj, base_left_adj]),
                            spatial_ref
                        )
                    else:
                        # V-shaped open polyline arrowhead
                        arrow_geom = arcpy.Polyline(
                            arcpy.Array([base_left_adj, tip_adj, base_right_adj]),
                            spatial_ref
                        )

                    # Automated QA/QC Inversion Check
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

        arcpy.AddMessage("Successfully generated {} flow direction arrows ({}).".format(feature_count, fc_geom_type))
        if reversed_count > 0:
            arcpy.AddWarning("QA/QC Alert: Detected {} pipe(s) with reversed flow direction against gravity!".format(reversed_count))

        # Assign derived parameter value for automatic map rendering
        parameters[7].value = output_layer

        # Explicit map rendering fallback
        try:
            if hasattr(arcpy, "mp"):
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                m = aprx.activeMap or (aprx.listMaps()[0] if aprx.listMaps() else None)
                if m:
                    m.addDataFromPath(output_layer)
            elif hasattr(arcpy, "mapping"):
                mxd = arcpy.mapping.MapDocument("CURRENT")
                df = arcpy.mapping.ListDataFrames(mxd)[0]
                lyr = arcpy.mapping.Layer(output_layer)
                arcpy.mapping.AddLayer(df, lyr)
                arcpy.RefreshTOC()
                arcpy.RefreshActiveView()
        except Exception:
            pass
