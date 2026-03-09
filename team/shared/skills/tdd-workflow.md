# 共享技能: TDD 工作流

## 标准流程

1. **RED** - 写一个失败的测试
```python
def test_parse_url_extracts_domain():
    result = parse_url("https://example.com/path")
    assert result.domain == "example.com"
```

2. **GREEN** - 写最小代码让测试通过
```python
def parse_url(url: str) -> ParsedUrl:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return ParsedUrl(domain=parsed.netloc)
```

3. **REFACTOR** - 优化代码，保持测试通过

## pytest 常用模式

### 参数化测试
```python
@pytest.mark.parametrize("input,expected", [
    ("https://example.com", "example.com"),
    ("http://sub.example.com:8080", "sub.example.com:8080"),
    ("", ""),
])
def test_parse_url(input, expected):
    assert parse_url(input).domain == expected
```

### Fixture
```python
@pytest.fixture
def sample_article():
    return Article(
        title="Test",
        url="https://example.com",
        content="Hello world",
    )
```

### Mock 外部依赖
```python
from unittest.mock import patch, AsyncMock

@patch("src.ai.analyzer.call_llm", new_callable=AsyncMock)
async def test_analyze(mock_llm):
    mock_llm.return_value = "summary text"
    result = await analyze("input")
    assert result == "summary text"
    mock_llm.assert_called_once()
```

## 运行测试
```bash
# 运行全部
python -m pytest tests/ -v

# 运行特定文件
python -m pytest tests/test_parsers.py -v

# 带覆盖率
python -m pytest tests/ --cov=src --cov-report=term-missing

# 只跑失败的
python -m pytest --lf
```
