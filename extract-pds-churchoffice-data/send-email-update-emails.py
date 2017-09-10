#!/usr/bin/env python3

import traceback
import smtplib
import base64
import csv
import re

from email.message import EmailMessage

single_email_base_url = 'https://form.jotform.us/72402423638149'
multi_email_base_url  = 'https://form.jotform.us/72402766938162'

smtp_server = 'smtp-relay.gmail.com'
smtp_from = '"Epiphany Catholic Church" <email-update@epiphanycatholicchurch.org>'
smtp_subject = 'Update your email address at Epiphany Catholic Church'

name_order = re.compile('^([^,]+),(.+)$')
name_squash1 = re.compile('\(.+\)')
name_squash2 = re.compile('\{.+\}')

member_email_filename = 'members-ge13-email-update-form.csv'
# Not currently sending to the family addresses
family_email_filename = 'members-ge13-email-family-update-form.csv'

with open(member_email_filename, 'r', newline='') as csvfile:
    fieldnames = ['ParKey', 'Member Name', 'PreferredEmail',
                  'OtherEmail1', 'OtherEmail2', 'OtherEmail3',
                  'OtherEmail4', 'OtherEmail5' ]
    reader = csv.DictReader(csvfile, fieldnames=fieldnames)
    first = True
    for row in reader:
        # Skip first row -- it's the headers
        if first:
            first = False
            continue

        # Fix a few things with names
        name = row['Member Name'].strip()

        # Remove all (foo) and {foo}
        name = name_squash1.sub('', name)
        name = name_squash2.sub('', name)

        # Some names are "Last,First".  Change that to "First Last"
        m = name_order.match(name)
        if m:
            first_name = m.group(2)
            full_name = "{first} {last}".format(last=m.group(1),
                                                first=m.group(2))
        else:
            words = name.split(' ')
            first_name = words[0]
            full_name = name

        # If we don't do this wonky value for the Family ID, the
        # resulting Google Sheet from the form submission will strip
        # off the leading zeros.  :-(
        parkey = "' {}".format(str(row['ParKey']).strip())

        print("Sending to: {fullname} ({salutation}) at {email}"
              .format(fullname=full_name,
                      salutation=first_name, email=row['PreferredEmail']))

        # If the Member has a single email address, use one form.  If
        # they have multiple addresses, use a different form.
        # Multiple email addresses
        if 'OtherEmail1' in row and row['OtherEmail1'] != '':
            we_have = row['PreferredEmail']
            if row['OtherEmail1']:
                we_have = we_have + '%0d' + row['OtherEmail1']
            if row['OtherEmail2']:
                we_have = we_have + '%0d' + row['OtherEmail2']
            if row['OtherEmail3']:
                we_have = we_have + '%0d' + row['OtherEmail3']
            if row['OtherEmail4']:
                we_have = we_have + '%0d' + row['OtherEmail4']
            if row['OtherEmail5']:
                we_have = we_have + '%0d' + row['OtherEmail5']

            url = ("{base}?"
                   "familyIdenvelope={parkey}&"
                   "yourName30={name}&"
                   "weHave={we_have}&"
                   "whichEmail={preferred}&"
                   "preferredEmail8={preferred}"
                   .format(base=multi_email_base_url,
                           parkey=parkey,
                           we_have=we_have,
                           name=full_name,
                           preferred=row['PreferredEmail']))

        # Single email address
        else:
            url = ("{base}?"
                   "familyIdenvelope={parkey}&"
                   "yourName30={name}&"
                   "preferredEmail={preferred}&"
                   "preferredEmail8={preferred}"
                   .format(base=single_email_base_url,
                           parkey=parkey,
                           name=full_name,
                           preferred=row['PreferredEmail']))

        message_body = ("""<html><body>
<p>
<img src="http://jeff.squyres.com/ecc/email-graphic.jpg" alt="" align="left" scale="0" style="margin: 0px 20px; height: 75px">
Dear {name}:</p>

<p>In an effort to improve communications with the parish, the office
has been reviewing the parishioner email addresses we have on file.
It appears that some of our parishioners may not have been receiving
our parish-wide emails and some of the email addresses may not be
up-to-date.  <strong>We need your help to fix that!</strong></p>

<p>Specifically, we want to make sure that we have a correct email
addresses for you.  If this communication has reached you at the wrong
-- or a less-preferred -- email address, please click on the link below
and update it.  Once you click on the link, you can check what we have
on file, make changes if necessary, and have the option to
"unsubscribe".  (Though we hope you will choose to continue to receive
our emails.)</p>

<p>If you have any changes to make, <em>please click the link below
and update your data before October 16, 2017.</em>.</p>

<p>We hope that you are as excited as we are to share with you the
happenings at Epiphany Catholic Church.  Thank you for your continued
support of our parish - there are exciting improvements coming soon
and we look forward to sharing more with you.</p>

<p><strong><a href="{url}">CLICK HERE TO UPDATE YOUR EMAIL ADDRESS
WITH EPIPHANY</a></strong>.</p>

<p>Sincerely,</p>

<p>Mary A. Downs<br />
<em>Business Manager</em><br />
Epiphany Catholic Church<br />
502-245-9733 ext. 12</p></body></html>"""
                        .format(name=full_name, url=url))

        smtp_to = '"{name}" <{email}>'.format(name=name, email=row['PreferredEmail'])
        # JMS DEBUG
        #smtp_to = '"{name}" <{email}>'.format(name=name, email='tech-committee@epiphanycatholicchurch.org')
        # JMS DOUBLE DEBUG
        #smtp_to = '"{name}" <{email}>'.format(name=name, email='jsquyres@gmail.com')

        try:
            with smtplib.SMTP_SSL(host=smtp_server) as smtp:
                msg = EmailMessage()
                msg['Subject'] = smtp_subject
                msg['From'] = smtp_from
                msg['To'] = smtp_to
                msg.set_content(message_body)
                msg.replace_header('Content-Type', 'text/html')

                smtp.send_message(msg)
        except:
            print("==== Error with {email}"
                  .format(email=row['PreferredEmail']))
            print(traceback.format_exc())
