<p>A user could set a really weird first name, such as <a href="https://evil.com">Eve</a></p>
<div onclick="alert('XSS');">Make sure the HTML markup does not end up in the email</div>
<ul><li>Lists are allowed</li></ul>
<ol><li>Even ordered</li></ol>
Contact: me@me.com<br>
<strong>This is important</strong>
<iframe src="https://evil.com"></iframe>
<script>alert('XSS');</script>
<b data-malicious="1">Bold</b>
<i required>Italic</i>
<button>Foo
<html>Invalid HTML is ignored</body>
