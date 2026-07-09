interface LayerTogglesProps {
  layers: Record<string, boolean>;
  onToggle: (key: string) => void;
}

const LABELS: Record<string, string> = {
  fractals: "分型",
  strokes: "笔",
  segments: "线段",
  centers: "中枢",
  signals: "买卖点",
};

export function LayerToggles({ layers, onToggle }: LayerTogglesProps) {
  return (
    <div className="layer-toggles" aria-label="图层开关">
      {Object.entries(layers).map(([key, value]) => (
        <label key={key} className="toggle-row">
          <input type="checkbox" checked={value} onChange={() => onToggle(key)} />
          <span>{LABELS[key]}</span>
        </label>
      ))}
    </div>
  );
}
