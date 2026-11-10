import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "ExperimentPilot | 目标检测实验工作台",
  description: "核对对照实验、查看证据、审批补跑申请。",
};

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
