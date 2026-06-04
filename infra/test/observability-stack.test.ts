import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { ObservabilityStack } from '../lib/observability-stack';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';
import { AgentStack } from '../lib/agent-stack';
import { ApiStack } from '../lib/api-stack';

function build() {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
  });
  const agent = new AgentStack(app, 'Agent', { tools });
  const api = new ApiStack(app, 'Api', { tools, agent });
  const obs = new ObservabilityStack(app, 'Obs', { tools, api });
  return { obs, t: Template.fromStack(obs) };
}

test('creates one CloudWatch dashboard', () => {
  const { t } = build();
  t.resourceCountIs('AWS::CloudWatch::Dashboard', 1);
});

test('creates a 5xx alarm for the REST API', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::CloudWatch::Alarm', Match.objectLike({
    Namespace: 'AWS/ApiGateway',
    MetricName: '5XXError',
  }));
});

test('creates one error alarm per tool Lambda', () => {
  const { t } = build();
  // 9 Python tool Lambdas (load_data, blend_paths, price_book, plot,
  // lookup_use_case, run_chronos2, check_chronos2, run_baseline_mc,
  // check_baseline_mc) each get an Errors alarm = at least 9 tool alarms.
  const alarms = t.findResources('AWS::CloudWatch::Alarm');
  const lambdaErrorAlarms = Object.values(alarms).filter(
    (r: any) => r.Properties?.Namespace === 'AWS/Lambda' && r.Properties?.MetricName === 'Errors',
  );
  expect(lambdaErrorAlarms.length).toBeGreaterThanOrEqual(9);
});
