# Rhythm feasibility test

Which heart conditions can a lightweight detector find from one chest-strap lead at 130 Hz? Uncorrected NeuroKit2 beats, six rhythm features and two tiny logistic models, tested on PTB-XL, PhysioNet 2017 and MIT-BIH at each dataset's own rate and at the strap's 130 Hz integer microvolts, against a pass bar fixed before any run. Results: [RESULTS.md](RESULTS.md). Models and their Hugging Face card: [models/](models/). Research only: nothing here reaches the booth yet.

## Run it (Windows paths; on Mac and Linux use `.venv-research/bin/python`)

    py -3.12 -m venv .venv-research
    .venv-research/Scripts/python -m pip install -r research/rhythm/requirements.txt
    .venv-research/Scripts/python -m research.rhythm.download    # PhysioNet's S3 mirror, about 3 GB of small files
    .venv-research/Scripts/python -m research.rhythm.prepare     # the features, a few minutes on many cores
    .venv-research/Scripts/python -m research.rhythm.evaluate    # models/ and RESULTS.md
    .venv-research/Scripts/python -m research.rhythm.publish     # the model card; --upload publishes it (needs HF_TOKEN in .env)

Data: PTB-XL 1.0.3, PhysioNet/CinC Challenge 2017, MIT-BIH Arrhythmia Database (PhysioNet). This is not a medical device.
