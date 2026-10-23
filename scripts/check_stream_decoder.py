"""Prove a shorter ADTS probe preserves every decoded sample; synthetic input only."""
import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import time


async def decode(binary, frames, rate, probe):
    process = await asyncio.create_subprocess_exec(binary, '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-protocol_whitelist', 'pipe,fd', '-probesize', str(probe), '-analyzeduration', '0', '-f', 'aac', '-i', 'pipe:0',
        '-vn', '-f', 's16le', '-ar', '24000', '-ac', '1', '-flush_packets', '1', 'pipe:1',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    start=time.monotonic();first=None;output=bytearray()
    async def feed():
        for frame in frames:
            process.stdin.write(frame);await process.stdin.drain();await asyncio.sleep(1024/rate)
        process.stdin.close()
    writer=asyncio.create_task(feed())
    try:
        async with asyncio.timeout(15):
            while True:
                chunk=await process.stdout.read(4096)
                if not chunk:break
                if first is None:first=round((time.monotonic()-start)*1000)
                output.extend(chunk)
            await writer;await process.wait()
        assert process.returncode==0,(await process.stderr.read()).decode()
        assert output
        return bytes(output),first
    finally:
        writer.cancel();await asyncio.gather(writer,return_exceptions=True)
        if process.returncode is None:process.kill();await process.wait()


async def run(binary):
    results=[]
    for rate,channels in [(24000,1),(44100,2),(48000,1)]:
        encoded=subprocess.run([binary,'-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i',
            f'sine=frequency=731:sample_rate={rate}:duration=1','-ac',str(channels),'-c:a','aac','-b:a','48k','-f','adts','pipe:1'],
            capture_output=True,check=True).stdout
        frames=[];offset=0
        while offset<len(encoded):
            size=((encoded[offset+3]&3)<<11)|(encoded[offset+4]<<3)|(encoded[offset+5]>>5)
            assert size>=7 and offset+size<=len(encoded)
            frames.append(encoded[offset:offset+size]);offset+=size
        baseline,slow=await decode(binary,frames,rate,2048)
        optimized,fast=await decode(binary,frames,rate,32)
        assert baseline==optimized,'small probe changed audio samples'
        results.append({'source_rate':rate,'channels':channels,'baseline_ms':slow,'optimized_ms':fast,
                        'identical_samples':True,'pcm_bytes':len(optimized),'sha256':hashlib.sha256(optimized).hexdigest()})
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--ffmpeg',default=shutil.which('ffmpeg'));args=parser.parse_args()
    if not args.ffmpeg:parser.error('FFmpeg is required')
    asyncio.run(run(args.ffmpeg))
