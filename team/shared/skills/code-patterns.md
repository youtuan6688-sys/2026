# 共享技能: 代码模式

## Python API 模板
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class ItemCreate(BaseModel):
    name: str
    description: str = ""

@app.post("/items", status_code=201)
async def create_item(item: ItemCreate):
    # 验证 → 处理 → 返回
    result = {"id": "...", **item.model_dump()}
    return result
```

## 错误处理模式
```python
import logging
logger = logging.getLogger(__name__)

def safe_operation(func):
    """统一错误处理装饰器"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as e:
            logger.warning(f"参数错误: {e}")
            return {"error": str(e), "code": 400}
        except Exception as e:
            logger.error(f"未预期错误: {e}", exc_info=True)
            return {"error": "内部错误", "code": 500}
    return wrapper
```

## 文件操作模式
```python
from pathlib import Path

def read_safely(path: str) -> str | None:
    """安全读取文件，不存在返回 None"""
    p = Path(path)
    return p.read_text(encoding='utf-8') if p.exists() else None

def write_atomic(path: str, content: str) -> None:
    """原子写入，先写临时文件再重命名"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(content, encoding='utf-8')
    tmp.rename(p)
```
