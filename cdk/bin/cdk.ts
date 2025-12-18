#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { VonageAgentCoreStack } from '../lib/cdk-stack';
import { AwsSolutionsChecks, NagSuppressions } from 'cdk-nag';
import { Aspects } from 'aws-cdk-lib';

const app = new cdk.App();
Aspects.of(app).add(new AwsSolutionsChecks());

const stack = new VonageAgentCoreStack(app, 'VonageAgentCoreStack1', {
  /* If you don't specify 'env', this stack will be environment-agnostic.
   * Account/Region-dependent features and context lookups will not work,
   * but a single synthesized template can be deployed anywhere. */

  /* Uncomment the next line to specialize this stack for the AWS Account
   * and Region that are implied by the current CLI configuration. */
  // env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },

  /* Uncomment the next line if you know exactly what Account and Region you
   * want to deploy the stack to. */
  // env: { account: '123456789012', region: 'us-east-1' },

  /* For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html */
});

// Suppress cdk-nag warnings
NagSuppressions.addStackSuppressions(stack, [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'AWSLambdaBasicExecutionRole is the standard managed policy for Lambda execution',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'Wildcards required for: (1) bedrock-agentcore dynamic runtime ARNs, (2) CloudWatch Logs dynamic log streams, (3) Bedrock foundation models cross-region access, (4) AgentCore workload identities',
  },
  {
    id: 'AwsSolutions-APIG4',
    reason: 'Authorization is handled in Lambda via Vonage JWT validation',
  },
  {
    id: 'AwsSolutions-APIG1',
    reason: 'Access logging not required since lambda will log each request',
  },
  {
    id: 'AwsSolutions-L1',
    reason: 'Using Python 3.14 which is the latest stable runtime as of 12/17/25',
  },
]);