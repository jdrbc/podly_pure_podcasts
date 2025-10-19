After an ad is identified, the next chunk should include context from the previous chunk(s) so that the full ad can be processed.

E.g. BEFORE this change

------------

Chunk 1:

1- Blah blah blah
2- We'll be back after the break
3- How to buy shoes from shoe.com

segments 2 & 3 identified

Chunk 2

4- just go to shoe.com and 
5- use your credit card
6- And We're back
7- blah blah blah

(notice that it is harder to identify ads in chunk 2 because of the missing preamble)

------------

e.g. AFTER this change

Chunk 1:

1- Blah blah blah
2- We'll be back after the break
3- How to buy shoes from shoe.com

segments 2 & 3 identified

Chunk 2

1- Blah blah blah
2- We'll be back after the break
3- How to buy shoes from shoe.com
4- just go to shoe.com and 
5- use your credit card
6- And We're back
7- blah blah blah

(notice that chunk 2 was expanded and so it is easier to identify the full add)
