import boto3
import zipfile
import os
import json
import time
import subprocess
import shutil
from pathlib import Path

# AWS clients
lambda_client = boto3.client('lambda', region_name='us-west-2')
apigateway_client = boto3.client('apigateway', region_name='us-west-2')
dynamodb_client = boto3.client('dynamodb', region_name='us-west-2')
iam_client = boto3.client('iam', region_name='us-west-2')
s3_client = boto3.client('s3', region_name='us-west-2')

def create_lambda_zip():
    """Lambda関数のZIPファイルを作成"""
    print("Creating Lambda deployment package...")
    
    import subprocess
    import shutil
    
    # 一時ディレクトリを作成
    temp_dir = 'lambda_package'
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    # 依存関係をインストール
    print("Installing dependencies...")
    subprocess.run([
        'pip', 'install',
        '-r', 'backend/requirements.txt',
        '-t', temp_dir,
        '--quiet'
    ], check=True)
    
    # Pythonファイルをコピー
    for file in ['main.py', 'lambda_handler.py', '__init__.py']:
        src = os.path.join('backend', file)
        if os.path.exists(src):
            shutil.copy(src, temp_dir)
    
    # ZIPファイルを作成
    zip_path = 'lambda_function.zip'
    shutil.make_archive('lambda_function', 'zip', temp_dir)
    
    # 一時ディレクトリを削除
    shutil.rmtree(temp_dir)
    
    # ファイルサイズを確認
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"Created {zip_path} ({size_mb:.2f} MB)")
    
    if size_mb > 50:
        print("WARNING: Package size exceeds 50MB, deployment may fail")
    
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
    
    # ファイルサイズを確認
    file_size = os.path.getsize(zip_path)
    size_mb = file_size / (1024 * 1024)
    
    # 50MB以上の場合はS3経由でアップロード
    if size_mb > 50:
        print(f"Package size ({size_mb:.2f} MB) exceeds 50MB, using S3...")
        
        # S3バケットを作成
        bucket_name = f'lambda-deploy-{int(time.time())}'
        try:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': 'us-west-2'}
            )
            print(f"Created S3 bucket: {bucket_name}")
        except Exception as e:
            print(f"Error creating bucket: {e}")
            return None
        
        # S3にアップロード
        s3_key = 'lambda_function.zip'
        s3_client.upload_file(zip_path, bucket_name, s3_key)
        print(f"Uploaded to S3: s3://{bucket_name}/{s3_key}")
        
        code = {
            'S3Bucket': bucket_name,
            'S3Key': s3_key
        }
    else:
        with open(zip_path, 'rb') as f:
            zip_content = f.read()
        code = {'ZipFile': zip_content}
    
    try:
        print("Creating Lambda function...")
        if 'ZipFile' in code:
            response = lambda_client.create_function(
                FunctionName=function_name,
                Runtime='python3.11',
                Role=role_arn,
                Handler='lambda_handler.handler',
                Code=code,
                Environment={
                    'Variables': {
                        'DYNAMODB_TABLE': 'EventsTable'
                    }
                },
                Timeout=30,
                MemorySize=512
            )
        else:
            response = lambda_client.create_function(
                FunctionName=function_name,
                Runtime='python3.11',
                Role=role_arn,
                Handler='lambda_handler.handler',
                Code=code,
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
        if 'ZipFile' in code:
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=code['ZipFile']
            )
        else:
            response = lambda_client.update_function_code(
                FunctionName=function_name,
                S3Bucket=code['S3Bucket'],
                S3Key=code['S3Key']
            )
        function_arn = response['FunctionArn']
        print(f"Lambda function updated: {function_arn}")
        
        # 環境変数を更新
        lambda_client.update_function_configuration(
            FunctionName=function_name,
            Environment={
                'Variables': {
                    'DYNAMODB_TABLE': 'EventsTable'
                }
            }
        )
    
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
    
    # ルートにANYメソッドを追加
    apigateway_client.put_method(
        restApiId=api_id,
        resourceId=root_id,
        httpMethod='ANY',
        authorizationType='NONE'
    )
    
    # Lambda統合を設定（ルート用）
    lambda_uri = f'arn:aws:apigateway:us-west-2:lambda:path/2015-03-31/functions/{lambda_arn}/invocations'
    
    apigateway_client.put_integration(
        restApiId=api_id,
        resourceId=root_id,
        httpMethod='ANY',
        type='AWS_PROXY',
        integrationHttpMethod='POST',
        uri=lambda_uri
    )
    
    # プロキシリソースを作成
    proxy_resource = apigateway_client.create_resource(
        restApiId=api_id,
        parentId=root_id,
        pathPart='{proxy+}'
    )
    proxy_id = proxy_resource['id']
    
    # ANYメソッドを作成（プロキシ用）
    apigateway_client.put_method(
        restApiId=api_id,
        resourceId=proxy_id,
        httpMethod='ANY',
        authorizationType='NONE'
    )
    
    # Lambda統合を設定（プロキシ用）
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
