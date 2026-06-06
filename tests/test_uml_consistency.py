"""Tests for UML ↔ code consistency checks."""

from modules.uml_consistency import (
    check_uml_code_consistency,
    extract_code_types,
    extract_er_entities,
    extract_plantuml_types,
    extract_state_names,
)


JAVA_CODE = """
public interface Shape {
    void draw();
    void erase();
}
public class Circle implements Shape {
    public void draw() {}
    public void erase() {}
}
public class ShapeFactory {
    public Shape createShape(String type) { return null; }
}
"""


def test_extract_java_types():
    types = extract_code_types(JAVA_CODE, "java")
    assert "Shape" in types
    assert "Circle" in types
    assert "ShapeFactory" in types


def test_extract_plantuml_types():
    puml = """
    @startuml
    interface Shape
    class Circle
    class ShapeFactory
    @enduml
    """
    types = extract_plantuml_types(puml)
    assert types == {"Shape", "Circle", "ShapeFactory"}


def test_consistency_all_covered():
    diagrams = [{"plantuml": "@startuml\ninterface Shape\nclass Circle\nclass ShapeFactory\n@enduml"}]
    result = check_uml_code_consistency(JAVA_CODE, diagrams, language="java")
    assert result["ok"] is True
    assert not result["missing_in_uml"]


def test_consistency_missing_types():
    diagrams = [{"plantuml": "@startuml\nclass Circle\n@enduml"}]
    result = check_uml_code_consistency(JAVA_CODE, diagrams, language="java")
    assert result["ok"] is False
    assert "Shape" in result["missing_in_uml"]
    assert "ShapeFactory" in result["missing_in_uml"]


ER_PUML = """
@startuml
entity 学生 {
  *学号 : VARCHAR
  --
  姓名 : VARCHAR
}
entity 课程 {
  *课程号 : VARCHAR
}
entity 教师 {
  *工号 : VARCHAR
}
学生 ||--o{ 选课 : 课程
@enduml
"""


def test_extract_er_entities():
    entities = extract_er_entities(ER_PUML)
    assert entities == {"学生", "课程", "教师"}


STATE_PUML = """
@startuml
[*] --> 待支付 : 创建
待支付 --> 已支付 : 付款
已支付 --> 已发货
state 待支付 {
  待支付 : entry / 锁定库存
}
@enduml
"""


def test_extract_state_names():
    states = extract_state_names(STATE_PUML)
    assert "待支付" in states
    assert "已支付" in states
    assert "已发货" in states
    assert "[*]" not in states
