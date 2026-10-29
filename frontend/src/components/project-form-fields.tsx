/**
 * 文件职责：复用规划项目表单字段、校验规则和约束编辑界面。
 */

"use client";

import { Divider, Form, Input, InputNumber } from "antd";

import type { PlanningProject } from "@/lib/http/planning";

/** 定义`ProjectFormValues`数据契约，约束组件属性或接口响应字段。 */
export interface ProjectFormValues {
  name: string;
  category: string;
  target_market: string;
  target_user?: string;
  target_margin?: number;
  min_price?: number;
  max_price?: number;
  unit_cost?: number;
  logistics_cost?: number;
  platform_fee_rate?: number;
  tax_rate?: number;
  marketing_rate?: number;
  fixed_cost?: number;
  forecast_units?: number;
  supplier_name?: string;
  moq?: number;
  lead_time_days?: number;
  max_lead_time_days?: number;
}

/** 定义`managedConstraintKeys`模块常量或配置，供当前文件中的多个流程复用。 */
const managedConstraintKeys = [
  "target_user",
  "target_margin",
  "price_range",
  "unit_cost",
  "logistics_cost",
  "platform_fee_rate",
  "tax_rate",
  "marketing_rate",
  "fixed_cost",
  "forecast_units",
  "supplier_name",
  "moq",
  "lead_time_days",
  "max_lead_time_days",
] as const;

/** 实现`asRecord`辅助逻辑，集中处理页面展示或状态转换规则。 */
function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

/** 实现`numberValue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function numberValue(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

/** 实现`stringValue`辅助逻辑，集中处理页面展示或状态转换规则。 */
function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

/** 实现`projectToFormValues`辅助逻辑，集中处理页面展示或状态转换规则。 */
export function projectToFormValues(project: PlanningProject): ProjectFormValues {
  const constraints = project.constraints;
  const rawPriceRange = constraints.price_range;
  const priceRange = asRecord(rawPriceRange);
  const listPriceRange = Array.isArray(rawPriceRange) ? rawPriceRange : [];
  return {
    name: project.name,
    category: project.category,
    target_market: project.target_market,
    target_user: stringValue(constraints.target_user),
    target_margin:
      typeof constraints.target_margin === "number" ? constraints.target_margin * 100 : undefined,
    min_price: numberValue(priceRange.min ?? listPriceRange[0]),
    max_price: numberValue(priceRange.max ?? listPriceRange[1]),
    unit_cost: numberValue(constraints.unit_cost),
    logistics_cost: numberValue(constraints.logistics_cost),
    platform_fee_rate:
      typeof constraints.platform_fee_rate === "number"
        ? constraints.platform_fee_rate * 100
        : undefined,
    tax_rate:
      typeof constraints.tax_rate === "number" ? constraints.tax_rate * 100 : undefined,
    marketing_rate:
      typeof constraints.marketing_rate === "number"
        ? constraints.marketing_rate * 100
        : undefined,
    fixed_cost: numberValue(constraints.fixed_cost),
    forecast_units: numberValue(constraints.forecast_units),
    supplier_name: stringValue(constraints.supplier_name),
    moq: numberValue(constraints.moq),
    lead_time_days: numberValue(constraints.lead_time_days),
    max_lead_time_days: numberValue(constraints.max_lead_time_days),
  };
}

/** 实现`buildProjectConstraints`辅助逻辑，集中处理页面展示或状态转换规则。 */
export function buildProjectConstraints(
  values: ProjectFormValues,
  existing: Record<string, unknown> = {},
): Record<string, unknown> {
  const constraints = { ...existing };
  for (const key of managedConstraintKeys) {
    delete constraints[key];
  }
  if (values.target_user?.trim()) constraints.target_user = values.target_user.trim();
  if (values.target_margin !== undefined) constraints.target_margin = values.target_margin / 100;
  if (values.min_price !== undefined && values.max_price !== undefined) {
    constraints.price_range = { min: values.min_price, max: values.max_price };
  }
  for (const key of [
    "unit_cost",
    "logistics_cost",
    "fixed_cost",
    "forecast_units",
    "moq",
    "lead_time_days",
    "max_lead_time_days",
  ] as const) {
    if (values[key] !== undefined) constraints[key] = values[key];
  }
  for (const key of ["platform_fee_rate", "tax_rate", "marketing_rate"] as const) {
    if (values[key] !== undefined) constraints[key] = values[key] / 100;
  }
  if (values.supplier_name?.trim()) constraints.supplier_name = values.supplier_name.trim();
  return constraints;
}

/** 复用规划项目的品类、市场、目标和业务约束表单字段。 */
export function ProjectFormFields() {
  return (
    <>
      <Form.Item name="name" label="项目名称" rules={[{ required: true, message: "请输入项目名称" }]}>
        <Input placeholder="例如：2027 春季智能水杯规划" />
      </Form.Item>
      <div className="form-grid-two">
        <Form.Item name="category" label="商品品类" rules={[{ required: true, message: "请输入商品品类" }]}>
          <Input placeholder="智能水杯" />
        </Form.Item>
        <Form.Item name="target_market" label="目标市场" rules={[{ required: true, message: "请输入目标市场" }]}>
          <Input placeholder="中国 / 东南亚 / 美国" />
        </Form.Item>
      </div>
      <Form.Item name="target_user" label="目标用户">
        <Input placeholder="例如：一二线城市年轻白领" />
      </Form.Item>
      <div className="form-grid-three">
        <Form.Item name="target_margin" label="目标毛利率 (%)">
          <InputNumber min={0} max={100} className="full-width" />
        </Form.Item>
        <Form.Item
          name="min_price"
          label="最低售价"
          dependencies={["max_price"]}
          rules={[
            ({ getFieldValue }) => ({
              validator(_, value) {
                const maximum = getFieldValue("max_price") as number | undefined;
                return (value === undefined) === (maximum === undefined)
                  ? Promise.resolve()
                  : Promise.reject(new Error("请同时填写最低和最高售价"));
              },
            }),
          ]}
        >
          <InputNumber min={0} className="full-width" />
        </Form.Item>
        <Form.Item
          name="max_price"
          label="最高售价"
          dependencies={["min_price"]}
          rules={[
            ({ getFieldValue }) => ({
              validator(_, value) {
                const minimum = getFieldValue("min_price") as number | undefined;
                if ((value === undefined) !== (minimum === undefined)) {
                  return Promise.reject(new Error("请同时填写最低和最高售价"));
                }
                return value !== undefined && minimum !== undefined && value < minimum
                  ? Promise.reject(new Error("最高售价不能低于最低售价"))
                  : Promise.resolve();
              },
            }),
          ]}
        >
          <InputNumber min={0} className="full-width" />
        </Form.Item>
      </div>
      <Divider titlePlacement="start">财务测算参数</Divider>
      <div className="form-grid-three">
        <Form.Item name="unit_cost" label="单位采购成本">
          <InputNumber min={0} precision={2} className="full-width" />
        </Form.Item>
        <Form.Item name="logistics_cost" label="单位物流成本">
          <InputNumber min={0} precision={2} className="full-width" />
        </Form.Item>
        <Form.Item name="forecast_units" label="预计销量">
          <InputNumber min={1} precision={0} className="full-width" />
        </Form.Item>
      </div>
      <div className="form-grid-three">
        <Form.Item name="platform_fee_rate" label="平台费率 (%)">
          <InputNumber min={0} max={100} precision={2} className="full-width" />
        </Form.Item>
        <Form.Item name="tax_rate" label="税费率 (%)">
          <InputNumber min={0} max={100} precision={2} className="full-width" />
        </Form.Item>
        <Form.Item name="marketing_rate" label="营销费率 (%)">
          <InputNumber min={0} max={100} precision={2} className="full-width" />
        </Form.Item>
      </div>
      <Form.Item name="fixed_cost" label="项目固定投入">
        <InputNumber min={0} precision={2} className="full-width" />
      </Form.Item>
      <Divider titlePlacement="start">供应商参数</Divider>
      <Form.Item name="supplier_name" label="供应商名称">
        <Input placeholder="例如：华东智能制造有限公司" />
      </Form.Item>
      <div className="form-grid-three">
        <Form.Item name="moq" label="最小起订量 (MOQ)">
          <InputNumber min={1} precision={0} className="full-width" />
        </Form.Item>
        <Form.Item name="lead_time_days" label="预计交期 (天)">
          <InputNumber min={1} precision={0} className="full-width" />
        </Form.Item>
        <Form.Item name="max_lead_time_days" label="最长可接受交期 (天)">
          <InputNumber min={1} precision={0} className="full-width" />
        </Form.Item>
      </div>
    </>
  );
}
