# CoinLine ADSI repository rules

- Commit verified milestones as focused changes. Describe consequential behavior and the validation performed in each commit body.
- Use synthetic caller, account and provider records in tracked fixtures. Keep recordings, packet captures, local configuration, credentials, firmware images and proprietary material out of version control. Cite public protocol evidence and describe wire behavior in original language.
- On Windows, launch build and test commands through MSYS2 MINGW64 from the project root. Run the Linux service stack through Docker Compose.
- Preserve build trees, run directories, caches and captures. Use a fresh build directory when configuration drifts. Recursive deletes, force wipes and clean targets require an explicit user instruction naming the exact action and target. Never apply a recursive force wipe to a broad parent, drive root or wildcard target.
