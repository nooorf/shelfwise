// A rendering bug shows a way back instead of a blank page. Starting a new visitor clears
// whatever state broke the screen; the server keeps nothing it needs.
import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface State {
  failed: boolean
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Shelfwise screen error', error, info.componentStack)
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return (
      <div role="alert" className="grid h-full place-items-center p-8 text-center">
        <div className="max-w-sm">
          <p className="font-serif text-lg">Something went wrong on this screen.</p>
          <p className="mt-1 text-sm text-muted">Starting over usually fixes it.</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-4 rounded-md border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
          >
            Start over
          </button>
        </div>
      </div>
    )
  }
}
