import { Component, type ReactNode } from 'react';

type CanvasRenderBoundaryProps = {
  children: ReactNode;
  resetKey: string;
  onRenderError: (error: Error) => void;
};

type CanvasRenderBoundaryState = {
  hasError: boolean;
  resetKey: string;
};

export class CanvasRenderBoundary extends Component<CanvasRenderBoundaryProps, CanvasRenderBoundaryState> {
  state: CanvasRenderBoundaryState = {
    hasError: false,
    resetKey: this.props.resetKey,
  };

  static getDerivedStateFromError(): Partial<CanvasRenderBoundaryState> {
    return { hasError: true };
  }

  static getDerivedStateFromProps(
    props: CanvasRenderBoundaryProps,
    state: CanvasRenderBoundaryState,
  ): Partial<CanvasRenderBoundaryState> | null {
    if (props.resetKey !== state.resetKey) {
      return {
        hasError: false,
        resetKey: props.resetKey,
      };
    }

    return null;
  }

  componentDidCatch(error: Error) {
    this.props.onRenderError(error);
  }

  render() {
    if (this.state.hasError) {
      return <div className="h-full w-full rounded-3xl bg-slate-50 dark:bg-slate-950" aria-hidden="true" />;
    }

    return this.props.children;
  }
}
