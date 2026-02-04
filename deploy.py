import boto3
import zipfile
import os
import json
import time
from pathlib import Path

# AWS clients
lambda_client = boto3.client('lambda', region_name='us-west-2')
apigateway_client = boto3.client('apigateway', region_name='us-west-2')
dynamodb_client = boto3.client('dynamodb', region_name='us-west-2')
iam_client = boto3.client('iam', region_name='us-west-2')

def create_lambda_zip():
    """Lambda関数のZIPファイルを作成"""
    print("Creating Lambda deployment package...")
    zip_path = 'lambda_function.zip'
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # backend フォルダのファイルを追加
        for root, dirs, files in os.walk('backend'):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    arcname = os.path.basename(file_path)
                    zipf.write(file_path, arcname)
    
    print(f"Created {zip_path}")
    return zip_path

def create_dynamodb_table():
    """DynamoDBテーブルを作成"""
    print("Creating DynamoDB table...")
    try:
        response = dynamodb_client.create_table(
            TableName='EventsTable',
            KeySchema=[
                {'AttributeName': 'eventId', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'eventId', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        print("DynamoDB table created successfully")
        
        # テーブルがアクティブになるまで待機
        waiter = dynamodb_client.get_waiter('table_exists')
        waiter.wait(TableName='EventsTable')
        print("DynamoDB table is now active")
        
    except dynamodb_client.exceptions.ResourceInUseException:
        print("DynamoDB table already exists")

def create_lambda_role():
    """Lambda実行ロールを作成"""
    print("Creating Lambda execution role...")
    role_name = 'EventsApiLambdaRole'
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    try:
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description='Execution role for Events API Lambda'
        )
        role_arn = response['Role']['Arn']
        print(f"Created role: {role_arn}")
        
        # ポリシーをアタッチ
        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
        )
        
        # DynamoDBアクセスポリシーを作成してアタッチ
        dynamodb_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": [
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:Scan"
                ],
                "Resource": f"arn:aws:dynamodb:us-west-2:*:table/EventsTable"
            }]
        }
        
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName='DynamoDBAccess',
            PolicyDocument=json.dumps(dynamodb_policy)
        )
        
        # ロールが伝播するまで待機
        print("Waiting for role to propagate...")
        time.sleep(10)
        
        return role_arn
        
    except iam_client.exceptions.EntityAlreadyExistsException:
        print("Role already exists, getting ARN...")
        response = iam_client.get_role(RoleName=role_name)
        return response['Role']['Arn']

def create_or_update_lambda(role_arn, zip_path):
    """Lambda関数を作成または更新"""
    function_name = 'EventsApiFunction'
    
    with open(zip_path, 'rb') as f:
        zip_content = f.read()
    
    try:
        print("Creating Lambda function...")
        response = lambda_client.create_function(
            FunctionName=function_name,
            Runtime='python3.11',
            Role=role_arn,
            Handler='lambda_handler.handler',
            Code={'ZipFile': zip_content},
            Environment={
                'Variables': {
                    'DYNAMODB_TABLE': 'EventsTable'
                }
            },
            Timeout=30,
            MemorySize=512
        )
        function_arn = response['FunctionArn']
        print(f"Lambda function created: {function_arn}")
        
    except lambda_client.exceptions.ResourceConflictException:
        print("Lambda function already exists, updating...")
        response = lambda_client.update_function_code(
            FunctionName=function_name,
            ZipFile=zip_content
        )
        function_arn = response['FunctionArn']
        print(f"Lambda function updated: {function_arn}")
    
    return function_arn

def create_api_gateway(lambda_arn):
    """API Gatewayを作成"""
    print("Creating API Gateway...")
    
    # REST APIを作成
    api_response = apigateway_client.create_rest_api(
        name='EventsApi',
        description='Events Management API',
        endpointConfiguration={'types': ['REGIONAL']}
    )
    api_id = api_response['id']
    print(f"Created API: {api_id}")
    
    # ルートリソースを取得
    resources = apigateway_client.get_resources(restApiId=api_id)
    root_id = resources['items'][0]['id']
    
    # プロキシリソースを作成
    proxy_resource = apigateway_client.create_resource(
        restApiId=api_id,
        parentId=root_id,
        pathPart='{proxy+}'
    )
    proxy_id = proxy_resource['id']
    
    # ANYメソッドを作成
    apigateway_client.put_method(
        restApiId=api_id,
        resourceId=proxy_id,
        httpMethod='ANY',
        authorizationType='NONE'
    )
    
    # Lambda統合を設定
    lambda_uri = f'arn:aws:apigateway:us-west-2:lambda:path/2015-03-31/functions/{lambda_arn}/invocations'
    
    apigateway_client.put_integration(
        restApiId=api_id,
        resourceId=proxy_id,
        httpMethod='ANY',
        type='AWS_PROXY',
        integrationHttpMethod='POST',
        uri=lambda_uri
    )
    
    # デプロイ
    deployment = apigateway_client.create_deployment(
        restApiId=api_id,
        stageName='prod'
    )
    
    # Lambda権限を追加
    account_id = boto3.client('sts').get_caller_identity()['Account']
    source_arn = f'arn:aws:execute-api:us-west-2:{account_id}:{api_id}/*/*'
    
    try:
        lambda_client.add_permission(
            FunctionName='EventsApiFunction',
            StatementId='apigateway-invoke',
            Action='lambda:InvokeFunction',
            Principal='apigateway.amazonaws.com',
            SourceArn=source_arn
        )
    except lambda_client.exceptions.ResourceConflictException:
        print("Permission already exists")
    
    api_url = f'https://{api_id}.execute-api.us-west-2.amazonaws.com/prod'
    print(f"\nAPI deployed successfully!")
    print(f"API URL: {api_url}")
    
    return api_url

def main():
    print("Starting deployment...")
    
    # 1. DynamoDBテーブルを作成
    create_dynamodb_table()
    
    # 2. Lambda実行ロールを作成
    role_arn = create_lambda_role()
    
    # 3. Lambda ZIPを作成
    zip_path = create_lambda_zip()
    
    # 4. Lambda関数を作成/更新
    lambda_arn = create_or_update_lambda(role_arn, zip_path)
    
    # 5. API Gatewayを作成
    api_url = create_api_gateway(lambda_arn)
    
    # クリーンアップ
    os.remove(zip_path)
    
    print("\nDeployment complete!")
    print(f"Your API is available at: {api_url}")

if __name__ == '__main__':
    main()
