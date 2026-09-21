import { useCallback, useState } from "react";
import GraphList from "./components/GraphList";
import EditorCanvas from "./components/EditorCanvas";
import RunView from "./components/RunView";

type View =
  | { kind: "list" }
  | { kind: "edit"; graphId: number | null }
  | { kind: "run"; runId: number };

export default function App() {
  const [view, setView] = useState<View>({ kind: "list" });

  const goList = useCallback(() => setView({ kind: "list" }), []);
  const goEdit = useCallback(
    (graphId: number | null) => setView({ kind: "edit", graphId }),
    []
  );
  const goRun = useCallback((runId: number) => setView({ kind: "run", runId }), []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>DAG 任务编排调度平台</h1>
        <span className="subtitle">拖拽编排 · 拓扑调度 · 并发控制 · 失败重试 · 运行观测</span>
      </header>
      {view.kind === "list" && <GraphList onEdit={goEdit} onOpenRun={goRun} />}
      {view.kind === "edit" && (
        <EditorCanvas
          graphId={view.graphId}
          onBack={goList}
          onRunStarted={goRun}
          onSaved={(id) => setView({ kind: "edit", graphId: id })}
        />
      )}
      {view.kind === "run" && (
        <RunView runId={view.runId} onBack={goList} onEditGraph={goEdit} />
      )}
    </div>
  );
}
