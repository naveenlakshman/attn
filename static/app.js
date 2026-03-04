// Global IT Attendance - JS helpers
function selectAllPresent() {
  document.querySelectorAll('input[name="present_ids"]').forEach(cb => cb.checked = true);
}

function clearAllPresent() {
  document.querySelectorAll('input[name="present_ids"]').forEach(cb => cb.checked = false);
}