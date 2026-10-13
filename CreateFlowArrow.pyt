# -*- coding: utf-8 -*-
"""
CreateFlowArrow.pyt
-------------------
Python Toolbox متكامل لإنشاء أسهم اتجاه السريان لشبكات البنية التحتية (صرف صحي، صرف مطري، مياه جوفية).
يعمل مباشرة في ArcMap (10.1 وما بعده) و ArcGIS Pro دون الحاجة لربط ملفات خارجية أو ضبط مسارات وسيطة.

Author: أحمد إبراهيم (Ahmad Ibrahim)
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
        """تعريف صندوق الأدوات (Toolbox)"""
        self.label = "Create Flow Arrow Toolbox"
        self.alias = "FlowArrowToolbox"
        self.tools = [CreateFlowArrow]


class CreateFlowArrow(object):
    def __init__(self):
        """تعريف أداة إنشاء أسهم السريان"""
        self.label = "إنشاء أسهم اتجاه السريان (Create Flow Arrows)"
        self.description = (
            "أداة هندسية تقوم بإنشاء طبقة مضلعات (Polygon Arrows) تعبر عن اتجاه "
            "السريان لشبكات المواسير والأنابيب (صرف صحي، أمطار، ري، مياه جوفية) "
            "بناءً على اتجاه الرسم وتدقيق المناسيب الهندسية."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        """تحديد بارامترات وواجهة المستخدم للأداة"""

        # 0. طبقة خطوط المواسير المدخلة
        param0 = arcpy.Parameter(
            displayName="طبقة خطوط المواسير (Input Pipes Layer)",
            name="input_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )
        param0.filter.list = ["Polyline"]

        # 1. مكان الحفظ (Geodatabase أو Folder)
        param1 = arcpy.Parameter(
            displayName="قاعدة البيانات الجغرافية للحفظ (Output Geodatabase)",
            name="output_workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input"
        )

        # 2. اسم الطبقة الناتجة
        param2 = arcpy.Parameter(
            displayName="اسم الطبقة الناتجة (Output Layer Name)",
            name="output_layer_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        param2.value = "PIPES_FLOW_ARROWS"

        # 3. عرض قاعدة السهم بالمتر
        param3 = arcpy.Parameter(
            displayName="عرض قاعدة السهم بالمتر (Arrow Base Width)",
            name="triangle_base",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input"
        )
        param3.value = 2.0

        # 4. ارتفاع / طول السهم بالمتر
        param4 = arcpy.Parameter(
            displayName="طول/ارتفاع السهم بالمتر (Arrow Height/Length)",
            name="triangle_height",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input"
        )
        param4.value = 5.0

        # 5. خيار نقل البيانات الوصفية من المواسير
        param5 = arcpy.Parameter(
            displayName="نقل بيانات الماسورة إلى السهم (Transfer Pipe Attributes)",
            name="transfer_attributes",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        param5.value = True

        # 6. المخرج المشتق (Derived Output) لإضافته تلقائياً للخريطة
        param6 = arcpy.Parameter(
            displayName="طبقة الأسهم الناتجة (Output Arrows Layer)",
            name="output_feature_class",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output"
        )
        param6.parameterDependencies = [param1.name]

        return [param0, param1, param2, param3, param4, param5, param6]

    def isLicensed(self):
        """التحقق من توفر ترخيص ArcGIS"""
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        """تنفيذ الأداة"""
        input_layer = parameters[0].valueAsText
        output_workspace = parameters[1].valueAsText
        output_layer_name = parameters[2].valueAsText
        triangle_base = float(parameters[3].value)
        triangle_height = float(parameters[4].value)
        transfer_attributes = bool(parameters[5].value)

        # التحقق من وجود مسار الحفظ
        if not arcpy.Exists(output_workspace):
            arcpy.AddError(u"مسار الحفظ المحدد غير موجود: {}".format(output_workspace))
            return

        output_layer = os.path.join(output_workspace, output_layer_name)

        # حذف الطبقة السابقة إذا كانت موجودة
        if arcpy.Exists(output_layer):
            try:
                arcpy.Delete_management(output_layer)
                arcpy.AddMessage(u"تم حذف الطبقة السابقة التي تحمل نفس الاسم: {}".format(output_layer_name))
            except Exception:
                pass

        # استخراج نظام الإحداثيات
        desc = arcpy.Describe(input_layer)
        spatial_ref = desc.spatialReference
        sr_name = spatial_ref.name if spatial_ref else "Unknown"
        arcpy.AddMessage(u"نظام الإحداثيات المستخدم: {}".format(sr_name))

        # إنشاء Feature Class للمضلعات
        arcpy.CreateFeatureclass_management(
            out_path=output_workspace,
            out_name=output_layer_name,
            geometry_type="POLYGON",
            spatial_reference=spatial_ref
        )
        arcpy.AddMessage(u"تم إنشاء طبقة المضلعات الناتجة: {}".format(output_layer_name))

        # إضافة حقول التدقيق
        arcpy.AddField_management(output_layer, "ORIG_FID", "LONG", field_alias=u"Original Pipe FID")
        arcpy.AddField_management(output_layer, "QA_FLOW_STATUS", "TEXT", field_length=30,
                                 field_alias=u"حالة اتجاه السريان (QA/QC)")

        # استخراج الحقول لنقلها
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

                    # حساب زاوية المماس عند منتصف الماسورة
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

                    # رؤوس المثلث
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

                    # مركز ثقل المثلث وضبط الإزاحة للمنتصف
                    mid_tri_x = (base_left.X + base_right.X + tip.X) / 3.0
                    mid_tri_y = (base_left.Y + base_right.Y + tip.Y) / 3.0

                    off_x = mid_point.X - mid_tri_x
                    off_y = mid_point.Y - mid_tri_y

                    base_left_adj = arcpy.Point(base_left.X + off_x, base_left.Y + off_y)
                    base_right_adj = arcpy.Point(base_right.X + off_x, base_right.Y + off_y)
                    tip_adj = arcpy.Point(tip.X + off_x, tip.Y + off_y)

                    triangle = arcpy.Polygon(
                        arcpy.Array([base_left_adj, base_right_adj, tip_adj, base_left_adj]),
                        spatial_ref
                    )

                    # تدقيق المناسيب الهندسية
                    qa_status = u"Normal Flow"
                    if st_inv_field and end_inv_field:
                        try:
                            st_idx = fields_to_copy.index(st_inv_field)
                            end_idx = fields_to_copy.index(end_inv_field)
                            st_val = attr_values[st_idx]
                            end_val = attr_values[end_idx]
                            if st_val is not None and end_val is not None:
                                if float(st_val) < float(end_val):
                                    qa_status = u"REVERSED (تحذير: سريان عكسي)"
                                    reversed_count += 1
                        except Exception:
                            pass

                    insert_row = [triangle, orig_fid, qa_status] + attr_values
                    insert_cursor.insertRow(insert_row)
                    feature_count += 1

        arcpy.AddMessage(u"تم إنشاء {} سهم اتجاه سريان بنجاح!".format(feature_count))
        if reversed_count > 0:
            arcpy.AddWarning(u"تنبيه تدقيق الجودة (QA/QC): تم رصد {} ماسورة مرسومة بعكس اتجاه الانحدار الطبيعي!".format(reversed_count))

        # تعيين قيمة المخرج المشتق لإضافتها تلقائياً للخريطة
        parameters[6].value = output_layer

        # إضافة صريحة للخريطة النشطة في حال لم تتم إضافتها تلقائياً
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
