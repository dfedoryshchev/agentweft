import os

# what is actually in there, i keep guessing
d = os.environ.get('INBOX', '.')
for f in os.listdir(d):
    print(f, os.path.getsize(os.path.join(d, f)))
