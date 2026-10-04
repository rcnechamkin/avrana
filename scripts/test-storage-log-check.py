import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("storage",str(Path(__file__).with_name("storage-log-check.py")))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
invalid="device-mapper: snapshots: Snapshot is marked invalid.\n"
io="kernel: Buffer I/O error on dev dm-3, logical block 0, async page read"
mapping={"dm-3":m.SNAPSHOT_NAME}
assert m.classify(invalid+io,mapping)==([], [io], True)
assert m.classify(io,mapping)==([io], [], False)
assert m.classify(invalid+io,{"dm-3":"ubuntu--vg-ubuntu--lv"})==([io], [], True)
assert m.classify(invalid+io,{})==([io], [], True)
for bad in ["kernel: I/O error, dev sdb, sector 200", "kernel: EXT4-fs error (device sdb1): bad journal", "kernel: usb 2-1: reset SuperSpeed USB device", "kernel: I/O error on dev dm-3", "kernel: Buffer I/O error on dev dm-30, logical block 0, async page read"]:
    a,s,v=m.classify(invalid+io+"\n"+bad,mapping)
    assert a==[bad] and s==[io] and v
assert m.classify("kernel: normal boot",mapping)==([],[],False)
print("PASS storage classification: unrelated array, root-volume, unknown-device, USB and ext4 failures remain visible")

retired=(invalid.strip(),io)
assert m.classify(invalid+io,{},retired)==([], [io], False)
assert m.classify(invalid+io,mapping,retired)==([], [io], True)
new="later: Buffer I/O error on dev dm-3, logical block 0, async page read"
assert m.classify(invalid+io+"\n"+new,{},retired)==([new], [io], False)
assert m.classify(invalid+io+"\nlater: "+invalid.strip(),{},retired)[2]
for bad in ["I/O error, dev sdb, sector 1","EXT4-fs error (device dm-1)","usb 2-1: reset SuperSpeed USB device"]:
 assert m.classify(invalid+io+"\n"+bad,{},retired)==([bad], [io], False)
receipt={'boot_id':'boot-a','snapshot_name':m.SNAPSHOT_NAME,'origin_uuid':'origin','kernel_lines':list(retired)}
dm={'dm-1':m.ORIGIN_NAME};uuids={m.ORIGIN_NAME:'origin'}
assert m.retirement_lines(receipt,'boot-a',dm,uuids)==list(retired)
assert m.retirement_lines(receipt,'boot-b',dm,uuids)==[]
assert m.retirement_lines(receipt,'boot-a',mapping,uuids)==[]
assert m.retirement_lines(receipt,'boot-a',dm,{m.ORIGIN_NAME:'different'})==[]
try:
 m.retirement_lines(dict(receipt,kernel_lines=["I/O error, dev sdb"]),'boot-a',dm,uuids)
 raise AssertionError("unrelated receipt error accepted")
except ValueError:pass
print("PASS retirement boundaries: boot identity, origin identity, reactivation, reused dm number, new invalid events and unrelated failures")
