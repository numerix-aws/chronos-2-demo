import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export class StorageStack extends cdk.Stack {
  public readonly dataBucket: s3.IBucket;
  public readonly plotsBucket: s3.IBucket;
  public readonly tracesBucket: s3.IBucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const common: s3.BucketProps = {
      versioned: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    };

    this.dataBucket = new s3.Bucket(this, 'DataBucket', { ...common });

    this.plotsBucket = new s3.Bucket(this, 'PlotsBucket', {
      ...common,
      cors: [{
        allowedMethods: [s3.HttpMethods.GET],
        allowedOrigins: ['*'],
        allowedHeaders: ['*'],
        maxAge: 300,
      }],
    });

    this.tracesBucket = new s3.Bucket(this, 'TracesBucket', { ...common });
  }
}
