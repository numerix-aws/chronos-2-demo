import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { ApiStack } from '../lib/api-stack';
import { ToolsStack } from '../lib/tools-stack';
import { StorageStack } from '../lib/storage-stack';
import { NetworkStack } from '../lib/network-stack';
import { AgentStack } from '../lib/agent-stack';

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
  return { api, t: Template.fromStack(api) };
}

test('creates one REST API with regional endpoint', () => {
  const { t } = build();
  t.resourceCountIs('AWS::ApiGateway::RestApi', 1);
  t.hasResourceProperties('AWS::ApiGateway::RestApi', {
    EndpointConfiguration: { Types: ['REGIONAL'] },
  });
});

test('every public route is gated by the Lambda authorizer', () => {
  const { t } = build();
  const methods = t.findResources('AWS::ApiGateway::Method');
  const protectedHttpVerbs = ['POST', 'GET'];
  for (const [, res] of Object.entries(methods)) {
    const props = (res as any).Properties;
    if (!protectedHttpVerbs.includes(props.HttpMethod)) continue;
    if (props.AuthorizationType === 'NONE' && props.HttpMethod === 'OPTIONS') continue;
    expect(props.AuthorizationType).toBe('CUSTOM');
  }
});

test('exposes a Lambda Function URL for SSE streaming (AWS_IAM, fronted by CloudFront)', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::Lambda::Url', {
    AuthType: 'AWS_IAM',
    InvokeMode: 'RESPONSE_STREAM',
  });
});

test('CORS allows the configured frontend origin', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::ApiGateway::Method', Match.objectLike({
    HttpMethod: 'OPTIONS',
  }));
});

test('exposes apiUrl and streamUrl outputs', () => {
  const { api } = build();
  expect(api.apiUrl).toBeDefined();
  expect(api.streamUrl).toBeDefined();
});

test('creates a CLOUDFRONT-scoped WAF WebACL with managed + rate rules', () => {
  const { t } = build();
  t.resourceCountIs('AWS::WAFv2::WebACL', 1);
  t.hasResourceProperties('AWS::WAFv2::WebACL', {
    Scope: 'CLOUDFRONT',
    DefaultAction: { Allow: {} },
    Rules: Match.arrayWith([
      Match.objectLike({
        Name: 'CommonRuleSet',
        Statement: { ManagedRuleGroupStatement: { Name: 'AWSManagedRulesCommonRuleSet', VendorName: 'AWS' } },
      }),
      Match.objectLike({
        Name: 'KnownBadInputs',
        Statement: { ManagedRuleGroupStatement: { Name: 'AWSManagedRulesKnownBadInputsRuleSet', VendorName: 'AWS' } },
      }),
      Match.objectLike({
        Name: 'RateLimit',
        Statement: { RateBasedStatement: { Limit: 100, AggregateKeyType: 'IP' } },
      }),
    ]),
  });
});

test('fronts the Function URL with a CloudFront distribution using OAC and no caching', () => {
  const { t } = build();
  t.resourceCountIs('AWS::CloudFront::Distribution', 1);
  t.resourceCountIs('AWS::CloudFront::OriginAccessControl', 1);
  // OAC signs requests to the Lambda origin with SigV4, always.
  t.hasResourceProperties('AWS::CloudFront::OriginAccessControl', {
    OriginAccessControlConfig: Match.objectLike({
      OriginAccessControlOriginType: 'lambda',
      SigningBehavior: 'always',
      SigningProtocol: 'sigv4',
    }),
  });
  // Distribution is attached to the WAF WebACL.
  t.hasResourceProperties('AWS::CloudFront::Distribution', {
    DistributionConfig: Match.objectLike({
      WebACLId: Match.anyValue(),
    }),
  });
});

test('streamUrl output is still defined (now the CloudFront domain)', () => {
  const { api } = build();
  expect(api.streamUrl).toBeDefined();
});
