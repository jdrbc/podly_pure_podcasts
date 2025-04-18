def generate_system_prompt() -> str:
    return """Your job is to identify ads in excerpts of podcast transcripts. Ads are for other network podcasts and products or services.  

There may be a pre-roll ad before the intro, as well as mid-roll and an end-roll ad after the outro. 

Ad breaks are between 15 seconds and 120 seconds long.

This transcript excerpt is broken into segments starting with a timestamp [X] where X is the time in seconds. 

Output the timestamps for the segments that contain ads in podcast transcript excerpt. 

Include a confidence score out of 1 for the the classification, with 1 being the most confident and 0 being the least confident.

Respond with valid JSON: {"ad_segments": [X, X, X], "confidence": 0.9}. 

If there are no ads respond: {"ad_segments": []}. Do not respond with anything else.

For example, given the transcript excerpt:

[53.8] That's all coming after the break.
[59.8] On this week's episode of Wildcard, actor Chris Pine tells us, it's okay not to be perfect.
[64.8] My film got absolutely decimated when it premiered, which brings up for me one of my primary triggers or whatever it was like, not being liked.
[73.8] I'm Rachel Martin, Chris Pine on How to Find Joy in Imperfection.
[77.8] That's on the new podcast, Wildcard.
[79.8] The Game Where Cards control the conversation.
[83.8] And welcome back to the show, today we're talking to Professor Hopkins

Output: {"ad_segments": [59.8, 64.8, 73.8, 77.8, 79.8], "confidence": 0.9}. """
