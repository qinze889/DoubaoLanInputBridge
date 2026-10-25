"""Check the actual one-file service contains the timezone fallback resources."""
import sys
from PyInstaller.archive.readers import CArchiveReader

archive = CArchiveReader(sys.argv[1])
names = {name.replace('\\', '/') for name in archive.toc}
for zone in ['Asia/Shanghai', 'America/New_York']:
    assert 'tzdata/zoneinfo/'+zone in names, 'Missing packaged timezone: '+zone
print('Frozen Windows timezone resources: Shanghai and New York present')
