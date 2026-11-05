#!/usr/bin/env python3
"""
Generate IoT Malware EM Side-Channel Analysis Lab Setup Report
"""

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
import os

def create_report():
    doc = Document()

    # Set up styles
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(12)

    # Title
    title = doc.add_heading('IoT Malware Analysis Lab Setup Plan', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Subtitle
    subtitle = doc.add_paragraph('Electromagnetic Side-Channel Analysis Research Environment')
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.runs[0].italic = True

    doc.add_paragraph()

    # Document info
    info = doc.add_paragraph()
    info.add_run('Project: ').bold = True
    info.add_run('IoT Malware Detection using EM Side-Channel Analysis\n')
    info.add_run('Platform: ').bold = True
    info.add_run('Raspberry Pi 5 (ARM64) + VirtualBox\n')
    info.add_run('Author: ').bold = True
    info.add_run('Vietnam National University, Ho Chi Minh City\n')
    info.add_run('Date: ').bold = True
    info.add_run('September 2026')

    doc.add_page_break()

    # ===================
    # Table of Contents
    # ===================
    doc.add_heading('Table of Contents', 1)

    toc_items = [
        '1. Executive Summary',
        '2. Project Objectives',
        '3. System Architecture Overview',
        '4. Resource Requirements',
        '5. Phase 1: Basic Environment Setup',
        '6. Phase 2: REMnux Configuration',
        '7. Phase 3: ARM64 Emulation Setup',
        '8. Phase 4: Malware Analysis Workflow',
        '9. EM Trace Collection Pipeline',
        '10. Complete Workflow Diagram',
        '11. Comparison with Original Plan',
        '12. Next Steps'
    ]

    for item in toc_items:
        p = doc.add_paragraph(item)
        p.paragraph_format.left_indent = Inches(0.5)

    doc.add_page_break()

    # ===================
    # Executive Summary
    # ===================
    doc.add_heading('1. Executive Summary', 1)

    doc.add_paragraph(
        'This document outlines the optimized laboratory setup for IoT malware research '
        'using Electromagnetic (EM) Side-Channel Analysis. The plan addresses the '
        'limitations identified in the original proposal and provides a modern, efficient '
        'workflow for analyzing ARM64 malware targeting Raspberry Pi 5 platforms.'
    )

    doc.add_heading('Key Improvements Over Original Plan', 2)

    improvements_table = doc.add_table(rows=4, cols=2)
    improvements_table.style = 'Table Grid'

    hdr = improvements_table.rows[0].cells
    hdr[0].text = 'Aspect'
    hdr[1].text = 'Improvement'
    for cell in hdr:
        cell.paragraphs[0].runs[0].bold = True

    data = [
        ('Architecture', 'ARM64 (correct for Pi 5) instead of ARM32'),
        ('Download Size', '4.8 GB instead of 6.2 GB'),
        ('Virtualization Layers', '2 layers instead of 4 (no nested VM)'),
    ]

    for i, (aspect, improvement) in enumerate(data, 1):
        improvements_table.rows[i].cells[0].text = aspect
        improvements_table.rows[i].cells[1].text = improvement

    doc.add_page_break()

    # ===================
    # Project Objectives
    # ===================
    doc.add_heading('2. Project Objectives', 1)

    objectives = [
        'Build a secure sandbox environment for IoT malware analysis',
        'Establish ARM64 emulation capability matching Raspberry Pi 5 architecture',
        'Collect electromagnetic traces from actual hardware for machine learning',
        'Develop a dataset for classifying malware vs. goodware based on EM emissions',
        'Enable reproducible research methodology for EM side-channel analysis'
    ]

    for obj in objectives:
        p = doc.add_paragraph(obj, style='List Bullet')

    doc.add_heading('Target Platform Specifications', 2)

    specs_table = doc.add_table(rows=5, cols=2)
    specs_table.style = 'Table Grid'

    specs = [
        ('Platform', 'Raspberry Pi 5'),
        ('Architecture', 'ARM64 (aarch64, ARMv8.2-A)'),
        ('CPU', 'Broadcom BCM2712 (Cortex-A76)'),
        ('Memory', '4GB / 8GB LPDDR4X'),
        ('OS', 'Raspberry Pi OS 64-bit'),
    ]

    for i, (key, val) in enumerate(specs):
        specs_table.rows[i].cells[0].text = key
        specs_table.rows[i].cells[1].text = val
        specs_table.rows[i].cells[0].paragraphs[0].runs[0].bold = True

    doc.add_page_break()

    # ===================
    # System Architecture
    # ===================
    doc.add_heading('3. System Architecture Overview', 1)

    doc.add_paragraph(
        'The laboratory environment consists of three main components: VirtualBox-based '
        'analysis VMs, QEMU ARM64 emulation for pre-hardware testing, and physical '
        'Raspberry Pi 5 hardware for actual EM trace collection.'
    )

    doc.add_heading('Architecture Diagram', 2)

    arch_text = '''
+------------------------------------------------------------------+
|                        WINDOWS HOST                               |
|                                                                  |
|  +------------------------------------------------------------+ |
|  |                    VIRTUALBOX                                | |
|  |                                                            | |
|  |  +----------------------------------------------------+  | |
|  |  |              REMnux VM (Ubuntu-based)              |  | |
|  |  |                                                     |  | |
|  |  |  +----------------------------------------------+  |  | |
|  |  |  |      Static Analysis Tools                    |  |  | |
|  |  |  |      - Ghidra, YARA, strings, UPX            |  |  | |
|  |  |  +----------------------------------------------+  |  | |
|  |  |                                                     |  | |
|  |  |  +----------------------------------------------+  |  | |
|  |  |  |      QEMU User-Mode                          |  |  | |
|  |  |  |      qemu-aarch64-static                      |  |  | |
|  |  |  |      (Quick binary smoke test)               |  |  | |
|  |  |  +----------------------------------------------+  |  | |
|  |  |                                                     |  | |
|  |  |  +----------------------------------------------+  |  | |
|  |  |  |      QEMU System Emulation                   |  |  | |
|  |  |  |      qemu-system-aarch64                      |  |  | |
|  |  |  |                                               |  |  | |
|  |  |  |       +-> Ubuntu ARM64 VM                    |  |  | |
|  |  |  |           (Full system test)                  |  |  | |
|  |  |  +----------------------------------------------+  |  | |
|  |  +----------------------------------------------------+  | |
|  +------------------------------------------------------------+ |
|                                                                  |
|  +------------------------------------------------------------+ |
|  |           PHYSICAL HARDWARE (EM Acquisition)                 | |
|  |                                                            | |
|  |     Raspberry Pi 5 ----GPIO----> Oscilloscope               | |
|  |     (ARM64 actual)         (EM trace capture)              | |
|  +------------------------------------------------------------+ |
+------------------------------------------------------------------+
'''
    p = doc.add_paragraph(arch_text)
    p.runs[0].font.name = 'Courier New'
    p.runs[0].font.size = Pt(8)

    doc.add_page_break()

    # ===================
    # Resource Requirements
    # ===================
    doc.add_heading('4. Resource Requirements', 1)

    doc.add_heading('4.1 Downloadable Resources', 2)

    resources_table = doc.add_table(rows=3, cols=4)
    resources_table.style = 'Table Grid'

    hdr = resources_table.rows[0].cells
    hdr[0].text = 'Resource'
    hdr[1].text = 'Size'
    hdr[2].text = 'Download Link'
    hdr[3].text = 'Purpose'
    for cell in hdr:
        cell.paragraphs[0].runs[0].bold = True

    resources = [
        ('REMnux OVA', '~4 GB', 'docs.remnux.org/install/distro', 'Malware analysis VM'),
        ('Ubuntu ARM64 Cloud Image', '~800 MB', 'cloud-images.ubuntu.com/releases/24.04/release/', 'ARM64 emulation'),
    ]

    for i, (name, size, link, purpose) in enumerate(resources, 1):
        resources_table.rows[i].cells[0].text = name
        resources_table.rows[i].cells[1].text = size
        resources_table.rows[i].cells[2].text = link
        resources_table.rows[i].cells[3].text = purpose

    doc.add_heading('4.2 Total Storage Requirements', 2)

    storage_items = [
        'VirtualBox Installation: ~200 MB',
        'REMnux OVA (imported): ~10 GB (expanded from 4 GB)',
        'Ubuntu ARM64 Image: ~10 GB',
        'Malware Samples Directory: Variable',
        'EM Traces Dataset: Variable (typically 10-50 GB+)',
    ]

    for item in storage_items:
        doc.add_paragraph(item, style='List Bullet')

    doc.add_heading('4.3 Memory Requirements', 2)

    memory_table = doc.add_table(rows=4, cols=2)
    memory_table.style = 'Table Grid'

    memory_data = [
        ('Component', 'RAM Required'),
        ('Windows Host', '16 GB recommended (8 GB minimum)'),
        ('REMnux VM', '4 GB'),
        ('QEMU ARM64 VM (internal)', '2 GB'),
    ]

    for i, (comp, ram) in enumerate(memory_data):
        memory_table.rows[i].cells[0].text = comp
        memory_table.rows[i].cells[1].text = ram
        if i == 0:
            memory_table.rows[i].cells[0].paragraphs[0].runs[0].bold = True
            memory_table.rows[i].cells[1].paragraphs[0].runs[0].bold = True

    doc.add_page_break()

    # ===================
    # Phase 1
    # ===================
    doc.add_heading('5. Phase 1: Basic Environment Setup', 1)

    doc.add_heading('5.1 VirtualBox Installation', 2)

    p = doc.add_paragraph()
    p.add_run('Step 1: ').bold = True
    p.add_run('Download VirtualBox 7.0+ from https://www.virtualbox.org/wiki/Downloads')

    p = doc.add_paragraph()
    p.add_run('Step 2: ').bold = True
    p.add_run('Download Extension Pack (same page) for USB 2.0/3.0 support')

    p = doc.add_paragraph()
    p.add_run('Step 3: ').bold = True
    p.add_run('Install with default settings and restart Windows')

    doc.add_heading('5.2 Host-Only Network Configuration', 2)

    doc.add_paragraph('Run the following commands in PowerShell as Administrator:')

    code_block = '''cd "C:\\Program Files\\Oracle\\VirtualBox"

VBoxManage hostonlyif create
VBoxManage hostonlyif ipconfig "VirtualBox Host-Only Ethernet Adapter" --ip 192.168.56.1 --netmask 255.255.255.0
VBoxManage dhcpserver add --ifname "VirtualBox Host-Only Ethernet Adapter" --ip 192.168.56.100 --netmask 255.255.255.0 --enable'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('5.3 Create Directory Structure', 2)

    code_block = '''# Create folders
New-Item -ItemType Directory -Path "C:\\VMImages\\REMnux" -Force
New-Item -ItemType Directory -Path "C:\\VMImages\\ARM64" -Force
New-Item -ItemType Directory -Path "C:\\VMShares\\MalwareSamples" -Force'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('5.4 Download REMnux OVA', 2)

    doc.add_paragraph('Navigate to: https://docs.remnux.org/install/distro')
    doc.add_paragraph('Download the latest REMnux OVA file (remnux-v7.ova or similar)')
    doc.add_paragraph('Save to: C:\\VMImages\\REMnux\\')

    doc.add_heading('5.5 Import REMnux into VirtualBox', 2)

    steps = [
        'VirtualBox → File → Import Appliance',
        'Select the REMnux OVA file',
        'Configure settings:',
        '   - Memory: 4096 MB',
        '   - Network Adapter 1: Host-Only Adapter',
        '   - Network Adapter 2: NAT (for internet access)',
        'Click Import and wait for process to complete',
    ]

    for step in steps:
        doc.add_paragraph(step, style='List Bullet')

    doc.add_page_break()

    # ===================
    # Phase 2
    # ===================
    doc.add_heading('6. Phase 2: REMnux Configuration', 1)

    doc.add_heading('6.1 Initial Setup', 2)

    code_block = '''# Boot REMnux and login
# Default credentials: remnux / malware (or as configured)

# Update system
sudo apt-get update
sudo apt-get upgrade -y'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('6.2 Install QEMU', 2)

    code_block = '''# Check if qemu-user-static is already installed
qemu-aarch64-static --version

# If not installed, install QEMU packages
sudo apt-get install -y qemu-user-static qemu-system-arm qemu-utils

# Verify installation
qemu-system-aarch64 --version'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('6.3 Configure Shared Folders', 2)

    doc.add_paragraph('In VirtualBox:')
    steps = [
        'Select REMnux VM → Settings → Shared Folders',
        'Click + to add new folder',
        'Folder Path: C:\\VMShares\\MalwareSamples',
        'Folder Name: malware_samples',
        'Auto-mount: Yes',
        'Make Permanent: Yes',
    ]

    for step in steps:
        doc.add_paragraph(step, style='List Bullet')

    doc.add_paragraph('In REMnux terminal:')

    code_block = '''# Add user to vboxsf group
sudo usermod -aG vboxsf remnux

# Logout and login again for changes to take effect
# Access shared folder at: /media/sf_malware_samples/'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_page_break()

    # ===================
    # Phase 3
    # ===================
    doc.add_heading('7. Phase 3: ARM64 Emulation Setup', 1)

    doc.add_heading('7.1 Download Ubuntu ARM64 Cloud Image', 2)

    code_block = '''# In REMnux terminal
mkdir -p ~/arm64-vm/images
cd ~/arm64-vm/images

# Download Ubuntu 24.04 ARM64 cloud image
wget https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('7.2 Create Snapshot Disk', 2)

    code_block = '''# Create a snapshot (writeable) disk based on the downloaded image
qemu-img create -f qcow2 -F qcow2 -b ubuntu-24.04-server-cloudimg-arm64.img ubuntu-arm64-test.qcow2 10G

# Verify disk
qemu-img info ubuntu-arm64-test.qcow2'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('7.3 Create Startup Script', 2)

    code_block = '''# Create startup script
mkdir -p ~/arm64-vm
nano ~/arm64-vm/start-arm64.sh'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_paragraph('Add the following content:')

    script_content = '''#!/bin/bash
# start-arm64.sh - Boot Ubuntu ARM64 for malware testing

IMG_DIR="$HOME/arm64-vm/images"
DISK="${IMG_DIR}/ubuntu-arm64-test.qcow2"

echo "Starting ARM64 VM for malware testing..."
echo "SSH will be available on port 2222"

qemu-system-aarch64 \\
  -M virt \\
  -cpu cortex-a72 \\
  -smp 2 \\
  -m 2G \\
  -drive file=${DISK},if=virtio,format=qcow2 \\
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \\
  -device virtio-net-pci,netdev=net0 \\
  -nographic \\
  -serial mon:stdio

echo "VM stopped"'''

    p = doc.add_paragraph()
    run = p.add_run(script_content)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    code_block = '''# Make executable
chmod +x ~/arm64-vm/start-arm64.sh'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_page_break()

    # ===================
    # Phase 4
    # ===================
    doc.add_heading('8. Phase 4: Malware Analysis Workflow', 1)

    doc.add_heading('8.1 Level 1: Static Analysis (REMnux)', 2)

    doc.add_paragraph('Perform initial malware analysis safely inside the VM:')

    code_block = '''# Navigate to malware samples
cd /media/sf_malware_samples

# 1. Check file type
file malware_sample

# 2. View readable strings
strings malware_sample | less

# 3. Check if packed with UPX
upx -t malware_sample

# 4. Unpack if packed
upx -d malware_sample -o malware_sample_unpacked

# 5. View ELF header
readelf -h malware_sample_unpacked

# 6. Open in Ghidra for reverse engineering
ghidra malware_sample_unpacked'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('8.2 Level 2: Smoke Test (QEMU User-Mode)', 2)

    doc.add_paragraph('Quick test to see if binary executes:')

    code_block = '''# Test binary with user-mode emulation
qemu-aarch64-static malware_sample_unpacked

# If missing libraries, specify library path
qemu-aarch64-static -L /usr/aarch64-linux-gnu/ malware_sample_unpacked'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('8.3 Level 3: Full System Test (QEMU ARM64 VM)', 2)

    code_block = '''# Start ARM64 VM (in one terminal)
~/arm64-vm/start-arm64.sh

# In another terminal, copy malware to VM
scp -P 2222 malware_sample ubuntu@localhost:/home/ubuntu/

# SSH into VM
ssh -p 2222 ubuntu@localhost

# Inside ARM64 VM, make executable and run
chmod +x malware_sample
./malware_sample

# Monitor behavior
# - Network: sudo tcpdump -i eth0
# - Processes: ps aux | grep malware
# - Files: inotifywait -m /home/ubuntu/'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_page_break()

    # ===================
    # EM Trace Collection
    # ===================
    doc.add_heading('9. EM Trace Collection Pipeline', 1)

    doc.add_heading('9.1 Hardware Setup', 2)

    hw_table = doc.add_table(rows=5, cols=2)
    hw_table.style = 'Table Grid'

    hw_data = [
        ('Component', 'Connection'),
        ('Raspberry Pi 5', 'GPIO 17 (BCM) → Trigger Input'),
        ('EM Probe', 'Positioned near CPU chip'),
        ('Oscilloscope', 'Connected via SMA to probe output'),
        ('Host PC', 'Ethernet to Pi for SSH control'),
    ]

    for i, (comp, conn) in enumerate(hw_data):
        hw_table.rows[i].cells[0].text = comp
        hw_table.rows[i].cells[1].text = conn
        if i == 0:
            hw_table.rows[i].cells[0].paragraphs[0].runs[0].bold = True
            hw_table.rows[i].cells[1].paragraphs[0].runs[0].bold = True

    doc.add_heading('9.2 Transfer Malware to Pi', 2)

    code_block = '''# From REMnux VM
scp -P 22 malware_sample pi@192.168.x.x:/home/pi/malware_test/

# Or use shared folder if configured'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_heading('9.3 Execute with EM Collection', 2)

    code_block = '''# SSH to Pi 5
ssh pi@192.168.x.x

# Navigate to EM project
cd ~/EM/

# Run malware with GPIO trigger synchronization
python3 goodware_runner.py --task malware --sample /home/pi/malware_test/malware_sample --count 100 --duration 2.0 --gpio-pin 17'''

    p = doc.add_paragraph()
    run = p.add_run(code_block)
    run.font.name = 'Courier New'
    run.font.size = Pt(10)

    doc.add_page_break()

    # ===================
    # Complete Workflow
    # ===================
    doc.add_heading('10. Complete Workflow Diagram', 1)

    workflow_text = '''
+------------------------------------------------------------------+
|  STEP 1: DOWNLOAD MALWARE                                        |
|  Sources: VirusShare, Malware Bazaar, vx-underground              |
|  Location: C:\\VMShares\\MalwareSamples                           |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|  STEP 2: STATIC ANALYSIS (REMnux VM)                            |
|  - file, strings, readelf                                        |
|  - UPX unpack                                                    |
|  - Ghidra reverse engineering                                    |
|  - YARA rule scanning                                            |
|  Goal: Understand malware without execution                        |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|  STEP 3: SMOKE TEST (QEMU User-Mode)                            |
|  Command: qemu-aarch64-static ./malware_binary                   |
|  Goal: Does binary crash immediately?                             |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|  STEP 4: FULL SYSTEM TEST (QEMU ARM64 System)                    |
|  - Boot Ubuntu ARM64 VM                                          |
|  - Execute malware with full kernel and network                   |
|  - Monitor syscalls, network traffic                             |
|  Goal: Full behavioral analysis before hardware test              |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|  STEP 5: EM TRACE COLLECTION (Raspberry Pi 5 Hardware)           |
|  - Transfer malware to Pi 5                                      |
|  - Execute with GPIO trigger → Oscilloscope                      |
|  - Collect EM traces                                             |
|  Goal: Build dataset for ML training                             |
+------------------------------------------------------------------+
'''

    p = doc.add_paragraph(workflow_text)
    p.runs[0].font.name = 'Courier New'
    p.runs[0].font.size = Pt(9)

    doc.add_page_break()

    # ===================
    # Comparison
    # ===================
    doc.add_heading('11. Comparison with Original Plan', 1)

    doc.add_paragraph(
        'The following table summarizes the differences between the original '
        'Minimax proposal, Gemini\'s critique, and this optimized plan.'
    )

    compare_table = doc.add_table(rows=7, cols=4)
    compare_table.style = 'Table Grid'

    hdr = compare_table.rows[0].cells
    hdr[0].text = 'Aspect'
    hdr[1].text = 'Original Plan'
    hdr[2].text = 'Gemini Critique'
    hdr[3].text = 'This Plan'
    for cell in hdr:
        cell.paragraphs[0].runs[0].bold = True

    compare_data = [
        ('Download Size', '~6.2 GB', '~4 GB', '~4.8 GB'),
        ('Virtualization Layers', '4 layers (nested)', '1 layer (REMnux only)', '2 layers (VB + REMnux + QEMU)'),
        ('ARM Architecture', 'ARM32 (Debian Wheezy)', 'N/A', 'ARM64 (Ubuntu 24.04)'),
        ('Pi 5 Compatible', 'No', 'N/A', 'Yes'),
        ('ARM Emulation', 'Yes (QEMU system)', 'No', 'Yes (QEMU system)'),
        ('Nested VM', 'Yes (very slow)', 'No', 'No (direct)'),
    ]

    for i, row_data in enumerate(compare_data, 1):
        for j, cell_data in enumerate(row_data):
            compare_table.rows[i].cells[j].text = cell_data

    doc.add_page_break()

    # ===================
    # Next Steps
    # ===================
    doc.add_heading('12. Next Steps', 1)

    next_steps = [
        ('Step 1:', 'Install VirtualBox and create Host-Only Network'),
        ('Step 2:', 'Download and import REMnux OVA'),
        ('Step 3:', 'Configure REMnux with QEMU'),
        ('Step 4:', 'Download Ubuntu ARM64 cloud image'),
        ('Step 5:', 'Test the complete workflow with sample malware'),
        ('Step 6:', 'Connect Raspberry Pi 5 and oscilloscope'),
        ('Step 7:', 'Collect first EM traces with goodware_runner.py'),
    ]

    for step_num, step_desc in next_steps:
        p = doc.add_paragraph()
        p.add_run(step_num).bold = True
        p.add_run(' ' + step_desc)

    doc.add_heading('Contact and Support', 2)

    doc.add_paragraph(
        'For questions or support regarding this setup, refer to the project '
        'documentation or contact the research supervisor.'
    )

    # Save document
    output_path = r'C:\Users\VJU_LONGBCSE2023\Desktop\EM\IoT_Malware_EM_Lab_Setup_Plan.docx'
    doc.save(output_path)
    print(f'Report saved to: {output_path}')
    return output_path

if __name__ == '__main__':
    create_report()
