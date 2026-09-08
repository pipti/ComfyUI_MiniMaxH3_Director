// -*- coding: utf-8 -*-
/* H3 Script IO —— 给 H3ScriptLoader / H3ScriptExporter 加 UI 按钮与「工作流配套配置单」逻辑。
 *
 * - 自动把 Exporter 的 out_path 填成「同目录/<工作流名>_promote.h3dp」（依赖 app.ui.loadedWorkflow.path）。
 * - H3ScriptLoader：『浏览...』按钮（弹 tkinter 原生文件选择框选 .h3dp/.json）、『刷新』按钮（重跑图重读）。
 * - H3ScriptExporter：『保存』按钮（存到 out_path，默认 = 工作流同名 _promote.h3dp）、『另存为』按钮（存到 out_path）。
 *   保存/另存为走 /minimax/director/save_script 即时写盘，不触发导演台出片。
 *   『浏览...』选择框走 /minimax/director/select_script（独立子进程跑 tkinter，不阻塞主服务）。
 */
(function () {
  "use strict";

  const LOADER = "H3ScriptLoader";
  const EXPORTER = "H3ScriptExporter";

  function getWidget(node, name) {
    return (node.widgets || []).find((w) => w.name === name) || null;
  }

  function getLoadedWorkflowPath() {
    const ui = app.ui;
    if (ui && ui.loadedWorkflow && ui.loadedWorkflow.path) {
      return ui.loadedWorkflow.path;
    }
    const wf = app.workflow;
    if (wf && wf.path) return wf.path;
    return "";
  }

  function defaultPromotePath(workflowPath) {
    if (!workflowPath) return "";
    const norm = String(workflowPath).replace(/\\/g, "/");
    const slash = norm.lastIndexOf("/");
    if (slash < 0) return "";
    const dir = norm.substring(0, slash);
    const base = norm.substring(slash + 1).replace(/\.json$/i, "");
    if (!dir || !base) return "";
    return dir + "/" + base + "_promote.h3dp";
  }

function syncOutPathDefault(node) {
  // 只对 Exporter：out_path 为空时自动填「同目录/<工作流名>_promote.h3dp」
  if (node.type !== EXPORTER) return;
  const op = getWidget(node, "out_path");
  if (!op) return;
  if (op.value && String(op.value).trim()) return; // 已有值不覆盖
  const lp = getLoadedWorkflowPath();
  const def = defaultPromotePath(lp);
  if (def) {
    op.value = def;
    if (typeof op.callback === "function") op.callback(def);
  }
}

async function browseScriptPath(node) {
    const sp = getWidget(node, "script_path");
    const cur = sp && sp.value ? String(sp.value).trim() : "";
    console.log("[H3 Script IO] browseScriptPath click, current=", cur);
    try {
      const resp = await fetch("/minimax/director/select_script", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial: cur }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        console.error("[H3 Script IO] select_script HTTP error", resp.status, data);
        toast(data.error || ("HTTP " + resp.status), "error");
        return;
      }
      const path = data.path || "";
      console.log("[H3 Script IO] selected path=", path);
      if (!path) {
        // 用户取消：静默
        return;
      }
      if (sp) {
        sp.value = path;
        if (typeof sp.callback === "function") sp.callback(path);
      }
      toast("Selected: " + path, "info");
    } catch (e) {
      console.error("[H3 Script IO] browseScriptPath failed", e);
      toast("Select failed: " + (e && e.message ? e.message : e), "error");
    }
  }

  function toast(msg, type) {
    type = type || "info";
    try {
      if (app.ui && typeof app.ui.dialog === "function") {
        app.ui.dialog({ type: type, title: "H3 Script IO", message: msg });
        return;
      }
    } catch (e) {
      /* 某些版本无 dialog，降级 */
    }
    if (type === "error") {
      console.error("[H3 Script IO] " + msg);
      if (typeof alert === "function") alert(msg);
    } else {
      console.log("[H3 Script IO] " + msg);
    }
  }

  function getTimelineDataValue(node) {
    const inputs = node.inputs || [];
    const idx = inputs.findIndex((i) => i.name === "timeline_data");
    if (idx >= 0 && inputs[idx].link != null && app.graph && app.graph.links) {
      const link = app.graph.links[inputs[idx].link];
      if (link) {
        const on = app.graph.getNodeById(link.origin_id);
        const slot = link.origin_slot;
        if (on && on.outputs && on.outputs[slot] && on.outputs[slot].value != null) {
          return on.outputs[slot].value;
        }
      }
    }
    const w = getWidget(node, "timeline_data");
    return w ? w.value : "";
  }

  async function saveScriptViaRoute(node, outPath) {
    const tl = getTimelineDataValue(node);
    if (!tl || !String(tl).trim()) {
      toast("No timeline_data: run Director first (ensure timeline_data is linked to this node)", "error");
      return;
    }
    try {
      const resp = await fetch("/minimax/director/save_script", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          timeline_data: typeof tl === "string" ? tl : JSON.stringify(tl),
          out_path: outPath,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
      const op = getWidget(node, "out_path");
      if (op) {
        op.value = outPath;
        if (typeof op.callback === "function") op.callback(outPath);
      }
      toast(data.status || "Saved -> " + outPath, "info");
    } catch (e) {
      toast("Save failed: " + (e && e.message ? e.message : e), "error");
    }
  }

  function addScriptIOButtons(node, nodeName) {
    if (nodeName === LOADER) {
      node.addWidget("button", "Browse...", null, function () { browseScriptPath(node); });
      node.addWidget("button", "Reload", null, function () {
        try {
          app.queuePrompt();
        } catch (e) {
          console.warn(e);
        }
      });
      console.log("[H3 Script IO] Loader widgets added:", node.id, "count=", node.widgets.length);
    } else if (nodeName === EXPORTER) {
      node.addWidget("button", "Save", null, function () {
        const op = getWidget(node, "out_path");
        const target = op && op.value ? String(op.value).trim() : "";
        if (!target) {
          toast("out_path is empty: save workflow first (auto default), or fill out_path manually", "error");
          return;
        }
        saveScriptViaRoute(node, target);
      });
      node.addWidget("button", "Save As", null, function () {
        const op = getWidget(node, "out_path");
        const target = op && op.value ? String(op.value).trim() : "";
        if (!target) {
          toast("Please fill out_path first", "error");
          return;
        }
        saveScriptViaRoute(node, target);
      });
      console.log("[H3 Script IO] Exporter widgets added:", node.id, "count=", node.widgets.length);
    }
  }

  app.registerExtension({
    name: "ComfyUI.MiniMaxH3ScriptIO",
    async beforeRegisterNodeDef(nodeType, nodeData) {
      if (nodeData?.name !== LOADER && nodeData?.name !== EXPORTER) return;
      const onNodeCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function (...args) {
        const r = onNodeCreated ? onNodeCreated.apply(this, args) : undefined;
        syncOutPathDefault(this);
        addScriptIOButtons(this, nodeData.name);
        return r;
      };
      const onConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function (...args) {
        const r = onConfigure ? onConfigure.apply(this, args) : undefined;
        syncOutPathDefault(this);
        return r;
      };
    },
    loadedGraphNode(node) {
      if (node && (node.type === LOADER || node.type === EXPORTER)) {
        // 工作流加载后再补一次按钮（onNodeCreated 已触发的实例可能没拿到回调）
        if (!node.widgets || !node.widgets.find((w) => w.type === "button")) {
          addScriptIOButtons(node, node.type);
        }
        syncOutPathDefault(node);
      }
    },
    afterConfigureGraph() {
      const nodes = (app.graph && app.graph.nodes) || [];
      for (const node of nodes) {
        if (node && (node.type === LOADER || node.type === EXPORTER)) {
          if (!node.widgets || !node.widgets.find((w) => w.type === "button")) {
            addScriptIOButtons(node, node.type);
          }
          syncOutPathDefault(node);
        }
      }
    },
  });
  console.log("[H3 Script IO] extension registered (Loader/Exporter)");
})();
