import { AppLayout, ContentLayout, Header, SpaceBetween } from '@cloudscape-design/components';
import '@cloudscape-design/global-styles/index.css';

export function App() {
  return (
    <AppLayout
      navigationHide
      toolsHide
      content={
        <ContentLayout
          header={
            <Header variant="h1" description="Chronos-2 augmenting the Numerix Monte Carlo">
              Numerix × Chronos-2 Demo
            </Header>
          }
        >
          <SpaceBetween size="l">
            <section aria-label="Chat" role="region">
              {/* ChatPanel mounts here in Task 20 */}
              <Header variant="h2">Conversation</Header>
            </section>
            <section aria-label="What-if" role="region">
              {/* WhatIfForm mounts here in Task 22 */}
              <Header variant="h2">What-if parameters</Header>
            </section>
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
}
