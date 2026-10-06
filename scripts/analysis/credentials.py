"""Read explicitly supplied experiment credentials without executing shell text."""
from pathlib import Path
import shlex


def credentials(path):
    """Read only two named env values; never execute shell code or log their contents."""
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, separator, value = line.partition('=')
        if separator and key.strip() in ('BIGMODEL_API_KEY', 'DEEPSEEK_API_KEY'):
            tokens = shlex.split(value, comments=True)
            if len(tokens) > 1:
                raise ValueError('Credential values cannot contain unquoted whitespace')
            values[key.strip()] = tokens[0] if tokens else ''
    return values
