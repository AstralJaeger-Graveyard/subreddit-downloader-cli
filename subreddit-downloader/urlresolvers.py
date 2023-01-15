import abc

from asyncpraw import Reddit
from asyncpraw.models import Submission


class BaseUrlResolver:
    """
        This class serves as BaseUrlResolver, the purpose is to allow a more generic and abstracted approach for
        different behaviours concearning for Reddit submissions types like url submissions
        , self-text submissions and crossposts
    """
    def __init__(self, reddit: Reddit):
        self.reddit = reddit

    @abc.abstractmethod
    def resolve(self, sumbission: Submission) -> set[str]:
        """
            This method defines the behaviour to resolve urls from a submission.
            Params:
                submission (Submission): The submission to inspect
            Returns:
                urls (set[str]): A set of urls from the submission
        """
        pass


class StandardUrlResolver(BaseUrlResolver):

    def __init__(self, reddit: Reddit):
        super().__init__(reddit)

    async def resolve(self, submission: Submission) -> set[str]:

        urls = set()
        if hasattr(submission, "media_metadata"):
            image_dict = submission.media_metadata
            for image_item in image_dict.values():
                largest_image = image_item['s']
                if hasattr(largest_image, 'u'):
                    urls.add(largest_image['u'])
                elif hasattr(largest_image, 'mp4'):
                    urls.add(largest_image['mp4'])
                elif hasattr(largest_image, 'gif'):
                    urls.add(largest_image['gif'])
        else:
            urls.add(submission.url)
        return urls


class CrosspostUrlResolver(BaseUrlResolver):

    def __init__(self, reddit: Reddit):
        super().__init__(reddit)

    async def resolve(self, submission: Submission) -> set[str]:
        if hasattr(submission, "crosspost_parent") and submission.crosspost_parent is not None:
            return await StandardUrlResolver(self.reddit)\
                .resolve(await self.reddit.submission(url = f"https://www.reddit.com{submission.permalink}"))
        return set()
