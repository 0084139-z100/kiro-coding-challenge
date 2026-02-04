import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import boto3
from botocore.exceptions import ClientError

app = FastAPI(title="Event Management API")

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DynamoDB設定
dynamodb = boto3.resource('dynamodb')
table_name = os.environ.get('DYNAMODB_TABLE', 'EventsTable')
table = dynamodb.Table(table_name)

# Pydanticモデル
class Event(BaseModel):
    eventId: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=200)
    descriptions: str = Field(..., min_length=1)
    date: str = Field(..., description="ISO format date")
    location: str = Field(..., min_length=1)
    capacity: int = Field(..., gt=0)
    organizer: str = Field(..., min_length=1)
    status: str = Field(..., pattern="^(draft|published|cancelled)$")

class EventUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    descriptions: Optional[str] = Field(None, min_length=1)
    date: Optional[str] = None
    location: Optional[str] = Field(None, min_length=1)
    capacity: Optional[int] = Field(None, gt=0)
    organizer: Optional[str] = Field(None, min_length=1)
    status: Optional[str] = Field(None, pattern="^(draft|published|cancelled)$")

@app.get("/")
def read_root():
    return {"message": "Event Management API", "version": "1.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/events", status_code=201)
def create_event(event: Event):
    try:
        event_id = str(uuid.uuid4())
        event_data = event.dict()
        event_data['eventId'] = event_id
        event_data['createdAt'] = datetime.utcnow().isoformat()
        
        table.put_item(Item=event_data)
        return event_data
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/events")
def list_events(status: Optional[str] = None):
    try:
        if status:
            # ステータスでフィルタリング
            response = table.scan(
                FilterExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': status}
            )
        else:
            response = table.scan()
        return {"events": response.get('Items', [])}
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/events/{event_id}")
def get_event(event_id: str):
    try:
        response = table.get_item(Key={'eventId': event_id})
        if 'Item' not in response:
            raise HTTPException(status_code=404, detail="Event not found")
        return response['Item']
    except HTTPException:
        raise
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.put("/events/{event_id}")
def update_event(event_id: str, event_update: EventUpdate):
    try:
        # 既存のイベントを確認
        response = table.get_item(Key={'eventId': event_id})
        if 'Item' not in response:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # 更新データを準備
        update_data = {k: v for k, v in event_update.dict().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        update_data['updatedAt'] = datetime.utcnow().isoformat()
        
        # DynamoDB更新式を構築
        update_expression = "SET " + ", ".join([f"#{k} = :{k}" for k in update_data.keys()])
        expression_attribute_names = {f"#{k}": k for k in update_data.keys()}
        expression_attribute_values = {f":{k}": v for k, v in update_data.items()}
        
        response = table.update_item(
            Key={'eventId': event_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
            ReturnValues="ALL_NEW"
        )
        return response['Attributes']
    except HTTPException:
        raise
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/events/{event_id}")
def delete_event(event_id: str):
    try:
        # 既存のイベントを確認
        response = table.get_item(Key={'eventId': event_id})
        if 'Item' not in response:
            raise HTTPException(status_code=404, detail="Event not found")
        
        table.delete_item(Key={'eventId': event_id})
        return {"message": "Event deleted successfully", "eventId": event_id}
    except HTTPException:
        raise
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
