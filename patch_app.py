import os

with open(r'dashboard\static\js\app.js', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''        // Animated pulse halo
        const pulse = (Date.now() % 1000) / 1000;
        ctx.beginPath();
        ctx.arc(cx, cy, 10 + (pulse * 10), 0, Math.PI*2);
        ctx.fillStyle = isEmergency ? `rgba(6, 182, 212, ${1-pulse})` : `rgba(156, 163, 175, ${0.5 - pulse*0.5})`;
        ctx.fill();

        // Core dot
        ctx.beginPath();
        ctx.arc(cx, cy, 6, 0, Math.PI*2);
        ctx.fillStyle = isEmergency ? '#06b6d4' : '#9ca3af';
        ctx.shadowColor = isEmergency ? '#06b6d4' : 'transparent';
        ctx.shadowBlur = isEmergency ? 10 : 0;
        ctx.fill();
        ctx.shadowBlur = 0; // reset

        // Label
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px sans-serif';
        ctx.fillText(aid, cx + 15, cy + 4);'''

replacement = '''        // Animated pulse halo
        const pulse = (Date.now() % 1000) / 1000;
        const isRedPhase = (Date.now() % 500) < 250;
        let haloColor, coreColor;
        if (isEmergency) {
            haloColor = isRedPhase ? `rgba(239, 68, 68, ${1-pulse})` : `rgba(6, 182, 212, ${1-pulse})`;
            coreColor = isRedPhase ? '#ef4444' : '#06b6d4';
        } else {
            haloColor = `rgba(156, 163, 175, ${0.5 - pulse*0.5})`;
            coreColor = '#9ca3af';
        }

        ctx.beginPath();
        ctx.arc(cx, cy, 10 + (pulse * 10), 0, Math.PI*2);
        ctx.fillStyle = haloColor;
        ctx.fill();

        // Core dot
        ctx.beginPath();
        ctx.arc(cx, cy, 6, 0, Math.PI*2);
        ctx.fillStyle = coreColor;
        ctx.shadowColor = isEmergency ? coreColor : 'transparent';
        ctx.shadowBlur = isEmergency ? 10 : 0;
        ctx.fill();
        ctx.shadowBlur = 0; // reset

        // Label
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px sans-serif';
        ctx.fillText(aid, cx + 15, cy + 4);

        // Destination Marker
        if (amb.target_position) {
            const tx = amb.target_position[0];
            const ty = amb.target_position[1];
            const tcx = getX(tx);
            const tcy = getY(ty);
            
            // Draw a dashed line from ambulance to destination
            ctx.beginPath();
            ctx.setLineDash([5, 5]);
            ctx.moveTo(cx, cy);
            ctx.lineTo(tcx, tcy);
            ctx.strokeStyle = `rgba(255, 255, 255, 0.3)`;
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.setLineDash([]);
            
            // Draw Destination Flag
            ctx.beginPath();
            ctx.arc(tcx, tcy, 4, 0, Math.PI*2);
            ctx.fillStyle = '#10b981'; // green for destination
            ctx.fill();
            ctx.fillStyle = '#10b981';
            ctx.fillText('DEST ' + aid, tcx + 8, tcy + 4);
        }'''

if target in text:
    text = text.replace(target, replacement)
    with open(r'dashboard\static\js\app.js', 'w', encoding='utf-8') as f:
        f.write(text)
    print('Done patching app.js!')
else:
    print('Target string not found in app.js!')
