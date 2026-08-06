RADIO OUTDOORS BUILD 0.38.8 - ADVENTURE STATUS FIX

Extract into C:\Projects\radiooutdoors-platform and overwrite files.

Run:
powershell -ExecutionPolicy Bypass -File .\Install_RadioOutdoors_0_38_8.ps1

Changes:
- Adds Adventure Status directly to the Edit Adventure form.
- Status can be changed between Active and Completed.
- Saving the Adventure saves the status with the other fields.
- Removes the unreliable separate status buttons.
- New Adventures still start as Active automatically.
