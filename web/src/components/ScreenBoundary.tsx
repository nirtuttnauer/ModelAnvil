import React, { type ReactNode } from 'react';
import { Button } from './ui';
import { Feedback } from './Feedback';

export class ScreenBoundary extends React.Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <Feedback state="error" title="This screen could not load." description="Check your connection and reload the app to retry."
        action={<Button type="button" onClick={() => window.location.reload()}>Reload app</Button>} />;
    }
    return <React.Suspense fallback={<Feedback state="loading" title="Loading screen…" />}>{this.props.children}</React.Suspense>;
  }
}
