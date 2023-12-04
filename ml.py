import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
from pydub import AudioSegment
import numpy as np

device = "cuda:0" if torch.cuda.is_available() else "cpu"
torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

model_id = "openai/whisper-large-v3"

model = AutoModelForSpeechSeq2Seq.from_pretrained(
    model_id, torch_dtype=torch_dtype, low_cpu_mem_usage=True, use_safetensors=True
)
model.to(device)

processor = AutoProcessor.from_pretrained(model_id)

pipe = pipeline(
    "automatic-speech-recognition",
    model=model,
    tokenizer=processor.tokenizer,
    feature_extractor=processor.feature_extractor,
    max_new_tokens=128,
    chunk_length_s=30,
    batch_size=16,
    return_timestamps=True,
    torch_dtype=torch_dtype,
    device=device,
)

def audioframe(f, normalized=False): 
  a = AudioSegment.from_file(f).set_frame_rate(16000)
  y = np.array(a.get_array_of_samples())
  if a.channels == 2:
      y = y.reshape((-1, 2))
  if normalized:
      return np.float32(y) / 2**15
  else:
      return y

def audio_to_text(audio_array):
    #audio_array = d.audioframe(f'{path}{files[5]}')
    
    #найдем стартовое  и итоговое значение и обрежем
    start = 0
    for a in range(len(audio_array)):
        if audio_array[a] > 0:
            start = a
            break
    
    end = 0
    for a in reversed(range(len(audio_array))):
        if audio_array[a] > 0:
            end = a
            break
    
    audio_array = audio_array[start:end]
    
    batchsize = 1000000
    start_value = 0
    text = ''
    while len(audio_array[start_value:start_value+batchsize]) > 0:
        #пайплайн распознавания
        try:
            result = pipe({'path': '0d38672e0bbdbdc460af55b8bb84a15b2730db2819f2af64f9c777d4d586f2de',
                          'array':audio_array[start_value:start_value+batchsize],
                          'sampling_rate': 16000})
            text += result["text"]
            start_value+=start_value+batchsize
        except:
            audio_array = audio_array[0:0]
            
    return text        
  