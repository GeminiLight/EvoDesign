'use client'
import React, { Component, ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

// 这是一个标准的 React 错误边界组件
class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  }

  // 当子组件抛出错误时，此生命周期方法会被调用
  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    if (typeof window !== 'undefined') {
      ;(window as any).__renderStatus = 'error'
      ;(window as any).__renderError = error?.message || String(error)
    }
    console.error('Tldraw rendering error caught by ErrorBoundary:', error, errorInfo)
  }

  public render() {
    if (this.state.hasError) {
      // 当发生错误时，渲染这个特定的 div
      // 服务端的 Playwright 将会寻找这个 id="render-error" 的元素
      return (
        <div id="render-error" style={{
            padding: '20px',
            color: '#c00',
            backgroundColor: '#fff0f0',
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap'
        }}>
          <h1>Tldraw Rendering Error</h1>
          <p>The provided JSON data is valid but could not be rendered by Tldraw.</p>
          <hr />
          <p><strong>Error Message:</strong></p>
          <pre>{this.state.error?.message ?? 'An unknown error occurred'}</pre>
        </div>
      )
    }

    // 如果没有错误，正常渲染子组件
    return this.props.children
  }
}

export default ErrorBoundary
