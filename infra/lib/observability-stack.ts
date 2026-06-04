import * as cdk from 'aws-cdk-lib';
import * as cw from 'aws-cdk-lib/aws-cloudwatch';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';
import { ToolsStack } from './tools-stack';
import { ApiStack } from './api-stack';

export interface ObservabilityStackProps extends cdk.StackProps {
  readonly tools: ToolsStack;
  readonly api: ApiStack;
}

export class ObservabilityStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);

    const apiName = 'chronos2-demo';

    // ---- API Gateway 5xx alarm.
    new cw.Alarm(this, 'Api5xxAlarm', {
      metric: new cw.Metric({
        namespace: 'AWS/ApiGateway',
        metricName: '5XXError',
        dimensionsMap: { ApiName: apiName, Stage: 'prod' },
        statistic: 'Sum',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 5,
      evaluationPeriods: 1,
      comparisonOperator: cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'API 5xx > 5 in 5 minutes',
    });

    // ---- Per-Lambda error + p95 duration alarm.
    const tool: Record<string, lambda.IFunction> = {
      load_data: props.tools.fnLoadData,
      blend_paths: props.tools.fnBlendPaths,
      price_book: props.tools.fnPriceBook,
      plot: props.tools.fnPlot,
      lookup_use_case: props.tools.fnLookupUseCase,
      run_chronos2: props.tools.fnRunChronos2,
      check_chronos2: props.tools.fnCheckChronos2,
      run_baseline_mc: props.tools.fnRunBaselineMc,
      check_baseline_mc: props.tools.fnCheckBaselineMc,
    };

    const dashboardWidgets: cw.IWidget[] = [];

    for (const [name, fn] of Object.entries(tool)) {
      new cw.Alarm(this, `Errors-${name}`, {
        metric: fn.metricErrors({ period: cdk.Duration.minutes(5), statistic: 'Sum' }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator: cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        alarmDescription: `${name} Lambda error`,
      });

      dashboardWidgets.push(
        new cw.GraphWidget({
          title: `${name} — invocations & errors`,
          left: [fn.metricInvocations({ statistic: 'Sum' })],
          right: [fn.metricErrors({ statistic: 'Sum' })],
          width: 12,
          height: 4,
        }),
      );
      dashboardWidgets.push(
        new cw.GraphWidget({
          title: `${name} — p95 duration`,
          left: [fn.metricDuration({ statistic: 'p95' })],
          width: 12,
          height: 4,
        }),
      );
    }

    // ---- SageMaker endpoint widgets (only useful if endpoint name is fixed).
    const endpointName =
      (this.node.tryGetContext('chronos2EndpointName') as string | undefined) ??
      'chronos2-endpoint';
    dashboardWidgets.push(
      new cw.GraphWidget({
        title: 'SageMaker — Chronos-2 invocations',
        left: [
          new cw.Metric({
            namespace: 'AWS/SageMaker',
            metricName: 'Invocations',
            dimensionsMap: { EndpointName: endpointName, VariantName: 'AllTraffic' },
            statistic: 'Sum',
          }),
        ],
        right: [
          new cw.Metric({
            namespace: 'AWS/SageMaker',
            metricName: 'ModelLatency',
            dimensionsMap: { EndpointName: endpointName, VariantName: 'AllTraffic' },
            statistic: 'p95',
          }),
        ],
        width: 24,
        height: 4,
      }),
    );

    new cw.Dashboard(this, 'Dashboard', {
      dashboardName: 'chronos2-demo',
      widgets: [dashboardWidgets],
    });

    new cdk.CfnOutput(this, 'DashboardUrl', {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=chronos2-demo`,
    });
  }
}
