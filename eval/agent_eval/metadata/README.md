# CVBench annotation metadata

`CVBench.json` is the unchanged annotation file previously stored in the vendored
CVBench/Video-R1 evaluation tree. MVAgent uses it to generate `QAs.json` and to map
saved question IDs to the three CVBench reporting categories. It contains no
model predictions or media.

Source: `Hokhim2/CVBench`, commit
`f8dc8f752fb8e7a3a05ac90e9ff9b3a9e90d79ed`,
`Video-R1/src/r1-v/Evaluation/CVBench.json`.
The accompanying source-tree license is preserved in `CVBench.LICENSE`.
The former model evaluation/training code is not needed by MVAgent and is removed.
