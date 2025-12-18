import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigatewayv2';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import * as path from 'path';
import * as agentcore from '@aws-cdk/aws-bedrock-agentcore-alpha';
import { DockerImageAsset } from 'aws-cdk-lib/aws-ecr-assets';
import * as dotenv from 'dotenv';

dotenv.config({ path: path.join(__dirname, '../../.env') });

export class VonageAgentCoreStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================
    // 1. Docker Image for Agent Container
    // ========================================
    const agentImage = new DockerImageAsset(this, 'AgentImage', {
      directory: path.join(__dirname, '../../runtime'),
    });

    // ========================================
    // 2. Lambda Function for Vonage Webhooks
    // ========================================
    const apiFn = new lambda.Function(this, "VonageApiHandler", {
      runtime: lambda.Runtime.PYTHON_3_14,
      architecture: lambda.Architecture.ARM_64,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../../lambda/api"), {
        bundling: {
          image: lambda.Runtime.PYTHON_3_13.bundlingImage,
          platform: "linux/arm64",
          command: [
            "bash", "-c",
            "pip install -r requirements.txt -t /asset-output && cp -r . /asset-output",
          ],
        },
      }),
      timeout: cdk.Duration.seconds(30),
    });


    apiFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream'],
      resources: ['*'],
    }));

    apiFn.addEnvironment('VONAGE_APPLICATION_ID', process.env.VONAGE_APPLICATION_ID!);


    // ========================================
    // 3. API Gateway - Vonage Webhook Endpoints
    // ========================================
    const api = new apigateway.HttpApi(this, 'VonageApi', {
      apiName: 'vonage-webhooks',
    });

    api.addRoutes({
      path: '/vonage/answer',
      methods: [apigateway.HttpMethod.GET],
      integration: new integrations.HttpLambdaIntegration('Answer', apiFn),
    });

    api.addRoutes({
      path: '/vonage/event',
      methods: [apigateway.HttpMethod.POST],
      integration: new integrations.HttpLambdaIntegration('Event', apiFn),
    });

    api.addRoutes({
      path: '/vonage/fallback',
      methods: [apigateway.HttpMethod.POST],
      integration: new integrations.HttpLambdaIntegration('Fallback', apiFn),
    });

    // ========================================
    // 4. AgentCore Runtime
    // ========================================
    const runtime = new agentcore.Runtime(this, 'NovaSonicRuntime', {
      runtimeName: 'vonage_nova_sonic',
      agentRuntimeArtifact: agentcore.AgentRuntimeArtifact.fromEcrRepository(
        agentImage.repository,
        agentImage.imageTag
      ),
    });

    runtime.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: ['arn:aws:bedrock:*::foundation-model/amazon.nova-sonic-v1:0', 'arn:aws:bedrock:*::foundation-model/amazon.nova-2-sonic-v1:0'],
    }));

    apiFn.addEnvironment('AGENT_RUNTIME_ARN', runtime.agentRuntimeArn);

    // ========================================
    // Outputs
    // ========================================
    new cdk.CfnOutput(this, 'AnswerUrl', {
      value: `${api.url}vonage/answer`,
    });

    new cdk.CfnOutput(this, 'EventUrl', {
      value: `${api.url}vonage/event`,
    });

    new cdk.CfnOutput(this, 'FallbackUrl', {
      value: `${api.url}vonage/fallback`,
    });

    new cdk.CfnOutput(this, 'ImageUri', {
      value: agentImage.imageUri,
    });

    new cdk.CfnOutput(this, 'RuntimeArn', {
      value: runtime.agentRuntimeArn,
    });
  }
}