import { CanvasLoadingScreen } from './DiagramCanvas/CanvasLoadingScreen';

type CanvasFallbackProps = {
  label: string;
};

export function CanvasFallback({ label }: CanvasFallbackProps) {
  return (
    <CanvasLoadingScreen>{label}</CanvasLoadingScreen>
  );
}

export default CanvasFallback;
