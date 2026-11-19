# 2.5D Mesh evaluation package

Use README.md and docs/USAGE.md. This is project-specific local postprocessing of completed remote evaluations, not training or remote inference.
For a formal M3 review run render on the registered fixed-ten inputs with actual task/checkpoint/code identities.
For primary_view=viewer or scene, actually inspect all 10 primary scene cards (GT/PRED plus the actual camera/LiDAR/Gaussian or projection panes present in that profile); comparison/diff grids are auxiliary. For legacy diagnostic runs inspect all 10 comparisons and 10 differences. Use tools that can read images; file hashes or generated text do not establish image inspection.
Fill review-template.json with reviewer_type=agent, original tool/call receipt references binding every primary image path and SHA256 (10 scene cards, or 20 legacy diagnostic paths), and classification/boundary/shape/matching/verdict per sample. Set inspected only after actual inspection. Never fabricate read receipts or copy historical judgments into a new run.
Use finalize then check; evaluation completeness and model quality are separate. complete+fail is a valid result. This M3 tool cannot declare M1/M2 or the overall research goal satisfied.
Preserve original outputs; use a new output directory for revisions. Do not start training, platform jobs, or timers to use this package.

Static exports must preserve equal XYZ scale [1,1,1]. Adjust camera angles, never exaggerate height. Default elevation=30 degrees from horizontal and azimuth=8 degrees along +X. Keep GT/PRED camera and uniform scale shared.

Point-cloud previews use pointcloud_visualize.py / pointcloud.cmd, accept the existing temporal metadata, and do not invoke formal fixed-ten finalization. Preserve semantic label-26 filtering and display sampling provenance. Never fabricate Mesh arrays to satisfy the fixed-ten protocol. When presenting generated previews, actually inspect every image being presented; file checks do not establish a visual quality judgment.

GitHub Actions are limited to static source and integrity checks; offline tests are maintainer-invoked. Never run training, inference, platform tasks, formal M3 review or release packaging in CI. Publishing distribution artifacts still requires release.cmd / local_release.py and its successful checks receipt. Local software verification does not imply a model-quality or formal M3 verdict.
