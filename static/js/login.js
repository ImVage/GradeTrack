function fillLogin(u, p) {
  document.getElementById('username').value = u;
  document.getElementById('password').value = p;
  document.getElementById('loginForm').submit();
}

function togglePw() {
  const inp = document.getElementById('password');
  inp.type = inp.type === 'password' ? 'text' : 'password';
}

document.querySelectorAll('.quick-chip[data-username]').forEach(chip => {
  chip.addEventListener('click', () => fillLogin(chip.dataset.username, chip.dataset.password));
});

const eyeButton = document.querySelector('.eye-btn');
if (eyeButton) {
  eyeButton.addEventListener('click', togglePw);
}
