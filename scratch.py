import yaml
from pathlib import Path

# what does safe_load actually give me back for the step list
for f in Path('flows').glob('*/flow.yaml'):
    print(f.parent.name, yaml.safe_load(f.read_text()).get('steps'))
