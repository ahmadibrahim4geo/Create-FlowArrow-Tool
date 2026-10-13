# -*- coding: utf-8 -*-
"""
CreateFlowArrow.py
------------------
أداة إنشاء أسهم اتجاه السريان لشبكات البنية التحتية (صرف صحي، صرف أمطار، تخفيض مياه جوفية)
متوافقة تماماً للعمل على كل من ArcMap (Python 2.7) و ArcGIS Pro (Python 3.x).

Author: أحمد إبراهيم (Ahmad Ibrahim)
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
# وظائف مساعدة للتوافق بين الإصدارات وطباعة الرسائل
# ---------------------------------------------------------------------------

def log_msg(msg):
    """طباعة رسالة عادية في نافذة الجيوسينج وعبر سطر الأوامر"""
    arcpy.AddMessage(msg)
    try:
        print(msg)
    except Exception:
        pass

def log_warn(msg):
    """طباعة رسالة تحذير"""
    arcpy.AddWarning(msg)
    try:
        print(u"[WARNING] " + msg)
    except Exception:
        pass

def log_err(msg):
    """طباعة رسالة خطأ"""
    arcpy.AddError(msg)
    try:
        print(u"[ERROR] " + msg)
    except Exception:
        pass

def add_to_active_map(layer_path):
    """
    إضافة الطبقة الناتجة تلقائياً إلى الخريطة النشطة الحالية
    يدعم كلاً من ArcGIS Pro (arcpy.mp) و ArcMap (arcpy.mapping)
    ويتخطى الخطوة بأمان عند التشغيل خارج واجهة المستخدم (Standalone/Script).
    """
    # 1. فحص بيئة ArcGIS Pro (arcpy.mp)
    if hasattr(arcpy, "mp"):
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = aprx.activeMap
            if not active_map:
                maps = aprx.listMaps()
                if maps:
                    active_map = maps[0]
            if active_map:
                active_map.addDataFromPath(layer_path)
                log_msg(u"✓ (ArcGIS Pro): تمت إضافة الطبقة بنجاح إلى الخريطة النشطة.")
                return True
            else:
                log_warn(u"لم يتم العثور على خريطة نشطة في مشروع ArcGIS Pro الحالي.")
        except Exception as e:
            # يحدث هذا عادة إذا كان السكربت يعمل خارج جلسة Pro تفاعلية
            log_msg(u"ملاحظة: السكربت يعمل خارج واجهة Pro، لم يتم ربط الخريطة تلقائياً.")
            return False

    # 2. فحص بيئة ArcMap (arcpy.mapping)
    elif hasattr(arcpy, "mapping"):
        try:
            mxd = arcpy.mapping.MapDocument("CURRENT")
            df = arcpy.mapping.ListDataFrames(mxd)[0]
            new_layer = arcpy.mapping.Layer(layer_path)
            arcpy.mapping.AddLayer(df, new_layer)
            arcpy.RefreshTOC()
            arcpy.RefreshActiveView()
            log_msg(u"✓ (ArcMap): تمت إضافة الطبقة بنجاح إلى إطار البيانات النشط.")
            return True
        except Exception as e:
            # يحدث هذا عادة إذا كان السكربت يعمل خارج ArcMap (مثلاً في سطر الأوامر)
            log_msg(u"ملاحظة: السكربت يعمل خارج واجهة ArcMap، لم يتم ربط الخريطة تلقائياً.")
            return False

    return False

# ---------------------------------------------------------------------------
# الدالة الرئيسية لتوليد أسهم اتجاه السريان
# ---------------------------------------------------------------------------

def create_flow_arrows(input_layer, output_workspace, output_layer_name,
                       triangle_base=2.0, triangle_height=5.0,
                       transfer_attributes=True):
    """
    الدالة الجوهرية لحساب وإنشاء أسهم اتجاه السريان.
    """
    # التحقق من وجود مسار الحفظ
    if not arcpy.Exists(output_workspace):
        log_err(u"مسار الحفظ المحدد غير موجود: {}".format(output_workspace))
        return None

    # التحقق من وجود الطبقة المدخلة
    if not arcpy.Exists(input_layer):
        log_err(u"طبقة المواسير المدخلة غير موجودة: {}".format(input_layer))
        return None

    output_layer = os.path.join(output_workspace, output_layer_name)

    # حذف الطبقة السابقة إن وجدت لتجنب أخطاء التعارض
    if arcpy.Exists(output_layer):
        try:
            arcpy.Delete_management(output_layer)
            log_msg(u"تم حذف الطبقة السابقة التي تحمل نفس الاسم: {}".format(output_layer_name))
        except Exception:
            pass

    # استخراج نظام الإحداثيات من الطبقة المدخلة
    desc = arcpy.Describe(input_layer)
    spatial_ref = desc.spatialReference
    sr_name = spatial_ref.name if spatial_ref else "Unknown"
    log_msg(u"نظام الإحداثيات المستخدم: {}".format(sr_name))

    # إنشاء Feature Class جديدة للمضلعات (POLYGON)
    arcpy.CreateFeatureclass_management(out_path=output_workspace,
                                        out_name=output_layer_name,
                                        geometry_type="POLYGON",
                                        spatial_reference=spatial_ref)
    log_msg(u"تم إنشاء طبقة أسهم الاتجاه الناتجة: {}".format(output_layer_name))

    # إضافة حقل المعرف الأصلي للربط (ORIG_FID)
    arcpy.AddField_management(output_layer, "ORIG_FID", "LONG",
                             field_alias=u"Original Pipe FID")

    # إضافة حقل فحص السريان العكسي (QA/QC Flag)
    arcpy.AddField_management(output_layer, "QA_FLOW_STATUS", "TEXT", field_length=30,
                             field_alias=u"حالة اتجاه السريان (QA/QC)")

    # فحص الحقول المتاحة في الطبقة المدخلة لنقلها إن طُلب ذلك
    input_fields = [f.name for f in arcpy.ListFields(input_layer)]
    input_field_objs = {f.name: f for f in arcpy.ListFields(input_layer)}

    # التحقق من وجود حقول المناسيب لإجراء التدقيق الهندسي
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
            # استبعاد الحقول الخاصة بالشكل والمعرف التلقائي
            if f_obj.type in ("OID", "Geometry") or f.upper().startswith("SHAPE"):
                continue
            if f.upper() in ("ORIG_FID", "QA_FLOW_STATUS"):
                continue
            try:
                arcpy.AddField_management(output_layer, f_obj.name, f_obj.type,
                                         field_precision=f_obj.precision,
                                         field_scale=f_obj.scale,
                                         field_length=f_obj.length,
                                         field_alias=f_obj.aliasName)
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

                # 1. استخراج نقطة البداية ونقطة النهاية للماسورة
                start_point = line.firstPoint
                end_point = line.lastPoint

                # 2. استخراج نقطة المنتصف بدقة
                mid_point = line.positionAlongLine(0.5, True).firstPoint

                # 3. حساب زاوية المماس عند منتصف الماسورة
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

                # 4. حساب إحداثيات رؤوس مثلث السهم
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

                # 5. حساب مركز ثقل المثلث (Centroid) ونقله ليتطابق مع منتصف الماسورة
                mid_triangle_x = (base_left.X + base_right.X + tip.X) / 3.0
                mid_triangle_y = (base_left.Y + base_right.Y + tip.Y) / 3.0

                offset_x = mid_point.X - mid_triangle_x
                offset_y = mid_point.Y - mid_triangle_y

                base_left_adj = arcpy.Point(base_left.X + offset_x, base_left.Y + offset_y)
                base_right_adj = arcpy.Point(base_right.X + offset_x, base_right.Y + offset_y)
                tip_adj = arcpy.Point(tip.X + offset_x, tip.Y + offset_y)

                # 6. بناء مضلع السهم
                triangle = arcpy.Polygon(arcpy.Array([base_left_adj, base_right_adj, tip_adj, base_left_adj]),
                                         spatial_ref)

                # 7. فحص اتجاه الانحدار الهندسي (QA/QC Elevation Inspection)
                qa_status = u"Normal Flow"
                if st_inv_field and end_inv_field:
                    try:
                        st_idx = fields_to_copy.index(st_inv_field)
                        end_idx = fields_to_copy.index(end_inv_field)
                        st_val = attr_values[st_idx]
                        end_val = attr_values[end_idx]
                        if st_val is not None and end_val is not None:
                            # في شبكات الانحدار، يجب أن يكون منسوب البداية أعلى من منسوب النهاية
                            if float(st_val) < float(end_val):
                                qa_status = u"REVERSED (تحذير: معكوس)"
                                reversed_count += 1
                    except Exception:
                        pass

                # 8. إدراج السجل في الطبقة الناتجة
                insert_row = [triangle, orig_fid, qa_status] + attr_values
                insert_cursor.insertRow(insert_row)
                feature_count += 1

    log_msg(u"تم إنشاء {} سهم اتجاه سريان بنجاح.".format(feature_count))
    if reversed_count > 0:
        log_warn(u"تنبيه تدقيق الجودة (QA/QC): تم اكتشاف {} ماسورة مرسومة بعكس اتجاه الانحدار الطبيعي!".format(reversed_count))

    # إضافة الطبقة إلى الخريطة التفاعلية النشطة
    add_to_active_map(output_layer)

    return output_layer

# ---------------------------------------------------------------------------
# نقطة الدخول عند استدعاء الأداة كـ Script Tool
# ---------------------------------------------------------------------------

def main():
    try:
        input_layer = arcpy.GetParameterAsText(0)
        output_workspace = arcpy.GetParameterAsText(1)
        output_layer_name = arcpy.GetParameterAsText(2)
        triangle_base = float(arcpy.GetParameterAsText(3))
        triangle_height = float(arcpy.GetParameterAsText(4))

        # معيار اختياري لنقل الحقول
        transfer_attrs = True
        if arcpy.GetArgumentCount() > 5:
            val = arcpy.GetParameterAsText(5)
            if val and val.lower() in ("false", "0", "no"):
                transfer_attrs = False

        create_flow_arrows(
            input_layer=input_layer,
            output_workspace=output_workspace,
            output_layer_name=output_layer_name,
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
