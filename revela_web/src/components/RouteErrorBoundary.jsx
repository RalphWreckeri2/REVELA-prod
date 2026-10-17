import { Component } from 'react';

export default class RouteErrorBoundary extends Component {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error('[route-error] Route rendering failed.', error, info.componentStack);
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <main className="route-loading route-error" role="alert">
        <h1>Page unavailable</h1>
        <p>We couldn't load this page. Check your connection, then reload to try again.</p>
        <button className="primary-btn" type="button" onClick={() => window.location.reload()}>
          Reload page
        </button>
      </main>
    );
  }
}