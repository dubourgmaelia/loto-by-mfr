import socket
import random
import qrcode
from flask import Flask, render_template_string, request, send_file
from flask_socketio import SocketIO, emit
from io import BytesIO

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

drawn_numbers = set()
claims_in_window = []
window_active = False
scores = {}  # {player_name: points}

PLAYER_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LotoMFR - Joueur</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #121218; color: white; text-align: center; margin: 0; padding: 10px; }
        h1 { color: #f5c518; margin-bottom: 5px; }
        .input-group { margin: 10px 0; }
        input[type="text"] { padding: 8px 12px; font-size: 1rem; border-radius: 6px; border: 1px solid #444; background: #222; color: white; text-align: center; }
        .card { display: grid; grid-template-columns: repeat(9, 1fr); gap: 4px; background: #f0eee1; padding: 6px; border-radius: 8px; margin: 15px 0; }
        .cell { aspect-ratio: 1; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 1.1rem; color: #14141e; border-radius: 4px; background: #fff; cursor: pointer; }
        .stamped { background: #22c55e !important; color: white !important; }
        .empty { background: transparent; cursor: default; }
        .btn { padding: 12px 20px; font-weight: bold; border: none; border-radius: 8px; font-size: 1rem; margin: 5px; cursor: pointer; }
        .btn-gold { background: #f5c518; color: #14141e; }
        #last-num { font-size: 3rem; font-weight: bold; color: #f5c518; margin: 10px 0; }
        #status-msg { font-size: 1.1rem; color: #38bdf8; min-height: 25px; margin: 10px 0; font-weight: bold; }
    </style>
</head>
<body>
    <h1>🎯 LotoMFR</h1>
    <div class="input-group">
        <input type="text" id="player-name" placeholder="Entre ton prénom" value="Joueur 1">
    </div>
    <div id="status-msg"></div>
    <div id="card" class="card"></div>
    <button class="btn btn-gold" onclick="claimWin('Quine')">🥉 Quine</button>
    <button class="btn btn-gold" onclick="claimWin('Double Quine')">🥈 Double Quine</button>
    <button class="btn btn-gold" onclick="claimWin('Carton Plein')">🏆 Carton Plein</button>
    <h3>Dernier numéro tiré :</h3>
    <div id="last-num">--</div>

    <script>
        const socket = io();
        let card = [];
        let drawnSet = new Set();
        let manualStamps = new Set();

        function generateCard() {
            card = Array(3).fill(null).map(() => Array(9).fill(null));
            let cols = [0,1,2,3,4,5,6,7,8];
            for(let r=0; r<3; r++) {
                let picked = cols.sort(() => 0.5 - Math.random()).slice(0, 5);
                picked.forEach(c => {
                    let min = c === 0 ? 1 : c * 10;
                    let max = c === 8 ? 90 : c * 10 + 9;
                    card[r][c] = Math.floor(Math.random() * (max - min + 1)) + min;
                });
            }
            manualStamps.clear();
            renderCard();
        }

        function renderCard() {
            const container = document.getElementById('card');
            container.innerHTML = '';
            for(let r=0; r<3; r++) {
                for(let c=0; c<9; c++) {
                    const div = document.createElement('div');
                    const val = card[r][c];
                    div.className = 'cell';
                    if(!val) div.classList.add('empty');
                    else {
                        div.innerText = val;
                        if(drawnSet.has(val) || manualStamps.has(val)) div.classList.add('stamped');
                        div.onclick = () => {
                            if(manualStamps.has(val)) manualStamps.delete(val);
                            else manualStamps.add(val);
                            renderCard();
                        };
                    }
                    container.appendChild(div);
                }
            }
        }

        socket.on('update_draw', (data) => {
            drawnSet = new Set(data.drawn);
            document.getElementById('last-num').innerText = data.last || '--';
            renderCard();
        });

        socket.on('claim_timer_start', (data) => {
            document.getElementById('status-msg').innerText = "⏱️ " + data.player + " réclame une " + data.type + " ! 5 secondes pour réclamer aussi !";
        });

        socket.on('win_result', (data) => {
            if (data.valid) {
                alert("🎉 Gagnant(s) pour " + data.type + " : " + data.winners.join(', '));
            } else {
                alert("❌ Réclamation invalide de la part de : " + data.player);
            }
            document.getElementById('status-msg').innerText = "";
        });

        socket.on('new_game_start', () => {
            document.getElementById('status-msg').innerText = "🔄 Nouvelle partie lancée ! Nouvelle grille générée.";
            generateCard();
            setTimeout(() => { document.getElementById('status-msg').innerText = ""; }, 4000);
        });

        function claimWin(type) {
            const name = document.getElementById('player-name').value || 'Joueur Anonyme';
            socket.emit('claim_win', { type: type, player: name, card: card });
        }

        generateCard();
    </script>
</body>
</html>
"""

LAUNCHER_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>LotoMFR - Console Lanceur</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #121218; color: white; display: flex; margin: 0; padding: 20px; gap: 20px; }
        .grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; width: 55%; }
        .btn-num { padding: 15px; font-weight: bold; background: #262632; color: white; border: none; border-radius: 8px; font-size: 1.1rem; cursor: pointer; }
        .btn-num.active { background: #22c55e !important; }
        .panel { width: 45%; background: #1c1c24; padding: 20px; border-radius: 12px; text-align: center; }
        #big-ball { font-size: 5rem; font-weight: bold; color: #f5c518; margin: 10px 0; }
        .btn-action { padding: 12px 20px; font-weight: bold; border: none; border-radius: 8px; font-size: 1rem; margin: 5px; cursor: pointer; }
        .btn-green { background: #22c55e; color: white; }
        .btn-red { background: #ef4444; color: white; }
        .qr-box { background: white; padding: 10px; display: inline-block; border-radius: 8px; margin-top: 5px; }
        .qr-box img { width: 140px; height: 140px; }
        #timer-box { font-size: 1.3rem; color: #ef4444; font-weight: bold; height: 35px; margin: 10px 0; }
        #podium { background: #121218; padding: 10px; border-radius: 8px; margin-top: 10px; text-align: left; }
        #podium h3 { margin: 0 0 5px 0; color: #f5c518; }
        .podium-item { margin: 3px 0; font-size: 0.95rem; }
    </style>
</head>
<body>
    <div class="grid" id="grid"></div>
    <div class="panel">
        <h2>🎤 CONSOLE LANCEUR</h2>
        <div>Dernier numéro :</div>
        <div id="big-ball">--</div>
        
        <div>
            <button class="btn-action btn-green" onclick="drawRandom()">🎲 Tirer un numéro au hasard</button>
            <button class="btn-action btn-red" onclick="resetGame()">🔄 Réinitialiser la Partie</button>
        </div>

        <div id="timer-box"></div>
        <div id="podium">
            <h3>🏆 Classement / Podium :</h3>
            <div id="podium-list">Aucun point pour le moment</div>
        </div>
        <hr style="border-color:#333; margin:15px 0;">
        <h3>📱 Flashez pour rejoindre :</h3>
        <div class="qr-box"><img src="/qr" alt="QR Code"></div>
        <p style="color:#aaa; font-size:0.85rem;">Ou sur le navigateur : <br><b id="ip-url"></b></p>
    </div>

    <script>
        const socket = io();
        let drawn = new Set();

        const grid = document.getElementById('grid');
        for(let i=1; i<=90; i++) {
            const btn = document.createElement('button');
            btn.className = 'btn-num';
            btn.id = 'num-' + i;
            btn.innerText = i;
            btn.onclick = () => toggleNum(i);
            grid.appendChild(btn);
        }

        function toggleNum(num) {
            socket.emit('toggle_number', { number: num });
        }

        function drawRandom() {
            socket.emit('draw_random');
        }

        function resetGame() {
            if(confirm("Réinitialiser le tirage manuel ?")) socket.emit('reset_game');
        }

        socket.on('update_draw', (data) => {
            drawn = new Set(data.drawn);
            document.getElementById('big-ball').innerText = data.last || '--';
            for(let i=1; i<=90; i++) {
                const el = document.getElementById('num-' + i);
                if(drawn.has(i)) el.classList.add('active');
                else el.classList.remove('active');
            }
        });

        socket.on('timer_tick', (data) => {
            document.getElementById('timer-box').innerText = data.msg;
        });

        socket.on('update_scores', (scores) => {
            const container = document.getElementById('podium-list');
            const sorted = Object.entries(scores).sort((a,b) => b[1] - a[1]);
            if(sorted.length === 0) {
                container.innerHTML = "Aucun point pour le moment";
                return;
            }
            let html = "";
            const medals = ["🥇", "🥈", "🥉"];
            sorted.forEach(([player, pts], idx) => {
                const icon = medals[idx] || "👤";
                html += `<div class="podium-item">${icon} <b>${player}</b> : ${pts} pts</div>`;
            });
            container.innerHTML = html;
        });

        document.getElementById('ip-url').innerText = window.location.href + 'player';
    </script>
</body>
</html>
"""

@app.route('/')
def launcher():
    return render_template_string(LAUNCHER_HTML)

@app.route('/player')
def player():
    return render_template_string(PLAYER_HTML)

@app.route('/qr')
def qr_code():
    # Génère l'URL dynamique du site web (fonctionne en local et sur Render/hébergeur)
    url = f"{request.host_url}player"
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@socketio.on('toggle_number')
def handle_toggle(data):
    num = data['number']
    if num in drawn_numbers:
        drawn_numbers.remove(num)
        last = list(drawn_numbers)[-1] if drawn_numbers else None
    else:
        drawn_numbers.add(num)
        last = num
    emit('update_draw', {'drawn': list(drawn_numbers), 'last': last}, broadcast=True)

@socketio.on('draw_random')
def handle_draw_random():
    available = [n for n in range(1, 91) if n not in drawn_numbers]
    if available:
        num = random.choice(available)
        drawn_numbers.add(num)
        emit('update_draw', {'drawn': list(drawn_numbers), 'last': num}, broadcast=True)

@socketio.on('reset_game')
def handle_reset():
    drawn_numbers.clear()
    emit('update_draw', {'drawn': [], 'last': None}, broadcast=True)

def verify_win(card, claim_type):
    completed_rows = 0
    for row in card:
        row_numbers = [num for num in row if num is not None]
        if all(num in drawn_numbers for num in row_numbers):
            completed_rows += 1

    if claim_type == 'Quine' and completed_rows >= 1:
        return True
    elif claim_type == 'Double Quine' and completed_rows >= 2:
        return True
    elif claim_type == 'Carton Plein' and completed_rows == 3:
        return True
    return False

@socketio.on('claim_win')
def handle_win(data):
    global window_active, claims_in_window
    
    player = data.get('player', 'Joueur Anonyme')
    claim_type = data.get('type')
    card = data.get('card')

    if not window_active:
        window_active = True
        claims_in_window = [{'player': player, 'card': card, 'type': claim_type}]
        emit('claim_timer_start', {'player': player, 'type': claim_type}, broadcast=True)
        
        for sec in range(5, 0, -1):
            socketio.emit('timer_tick', {'msg': f"⏱️ Attente des autres joueurs : {sec}s"}, broadcast=True)
            socketio.sleep(1)
        
        socketio.emit('timer_tick', {'msg': ""}, broadcast=True)
        
        valid_winners = []
        pts_map = {'Quine': 1, 'Double Quine': 2, 'Carton Plein': 5}
        
        for c in claims_in_window:
            if verify_win(c['card'], c['type']):
                if c['player'] not in valid_winners:
                    valid_winners.append(c['player'])
                    scores[c['player']] = scores.get(c['player'], 0) + pts_map.get(c['type'], 1)

        if valid_winners:
            socketio.emit('win_result', {'valid': True, 'winners': valid_winners, 'type': claim_type}, broadcast=True)
            socketio.emit('update_scores', scores, broadcast=True)
            
            if claim_type == 'Carton Plein':
                for sec in range(15, 0, -1):
                    socketio.emit('timer_tick', {'msg': f"🎆 CARTON PLEIN ! Nouvelle partie dans {sec}s"}, broadcast=True)
                    socketio.sleep(1)
                
                drawn_numbers.clear()
                socketio.emit('timer_tick', {'msg': ""}, broadcast=True)
                socketio.emit('update_draw', {'drawn': [], 'last': None}, broadcast=True)
                socketio.emit('new_game_start', broadcast=True)
        else:
            socketio.emit('win_result', {'valid': False, 'player': player}, broadcast=True)

        window_active = False
        claims_in_window = []
    else:
        claims_in_window.append({'player': player, 'card': card, 'type': claim_type})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)